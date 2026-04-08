#!/usr/bin/env python3
"""
Med Portfolio — Web UI + LinkedIn Integration

Run:  python app.py
Open: http://localhost:5051
"""

import os
import json
import time
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests as http_requests
from flask import (
    Flask, request, redirect, jsonify, render_template, session,
)

# Import from existing generate.py (this also loads .env)
from generate import (
    generate, read_last_shapes, write_last_shape,
    INBOX, DONE, SUPPORTED, CATEGORIES,
)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

BASE_DIR = Path(__file__).parent
TOKEN_PATH = BASE_DIR / "linkedin_token.json"

# LinkedIn config
LINKEDIN_CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
LINKEDIN_REDIRECT_URI = "http://localhost:5051/linkedin/callback"
LINKEDIN_SCOPES = "openid profile email w_member_social"

# Background generation state
generation_lock = threading.Lock()
generation_progress = {"running": False, "current": 0, "total": 0, "current_name": ""}


# ─── Helpers: metadata ────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_cert_id() -> str:
    return secrets.token_hex(4)


def read_metadata(folder: Path) -> dict | None:
    meta_path = folder / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    return None


def write_metadata(folder: Path, meta: dict):
    (folder / "metadata.json").write_text(json.dumps(meta, indent=2))


def make_metadata(cert_id: str, original_filename: str) -> dict:
    return {
        "cert_id": cert_id,
        "status": "uploaded",
        "original_filename": original_filename,
        "uploaded_at": now_iso(),
        "notes": None,
        "generated_at": None,
        "post_text": None,
        "category": None,
        "short_name": None,
        "confidence": None,
        "flag_reason": None,
        "shape_used": None,
        "char_count": None,
        "saved_at": None,
        "published_at": None,
        "linkedin_post_id": None,
        "last_error": None,
    }


def find_cert_file(folder: Path) -> Path | None:
    """Find the certificate file in a cert folder."""
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in SUPPORTED:
            return f
    return None


# ─── Helpers: gather all certs ────────────────────────────────────────

def get_all_certs() -> list[dict]:
    """Get all certs across inbox and done, with metadata."""
    certs = []

    # Certs in inbox (uploaded / generated)
    if INBOX.exists():
        for folder in sorted(INBOX.iterdir()):
            if not folder.is_dir():
                continue
            meta = read_metadata(folder)
            if meta:
                certs.append(meta)

    # Certs in done (saved / published)
    if DONE.exists():
        for category_dir in sorted(DONE.iterdir()):
            if not category_dir.is_dir():
                continue
            for post_dir in sorted(category_dir.iterdir()):
                if not post_dir.is_dir():
                    continue
                meta = read_metadata(post_dir)
                if meta:
                    certs.append(meta)
                else:
                    # Backward compat: infer from filesystem
                    post_file = post_dir / "post.md"
                    if post_file.exists():
                        text = post_file.read_text().strip()
                        certs.append({
                            "cert_id": post_dir.name,
                            "status": "saved",
                            "original_filename": None,
                            "uploaded_at": None,
                            "notes": None,
                            "generated_at": None,
                            "post_text": text,
                            "category": category_dir.name,
                            "short_name": post_dir.name,
                            "confidence": None,
                            "flag_reason": None,
                            "shape_used": None,
                            "char_count": len(text),
                            "saved_at": None,
                            "published_at": None,
                            "linkedin_post_id": None,
                            "last_error": None,
                        })

    return certs


def find_cert_folder(cert_id: str) -> Path | None:
    """Find a cert folder by ID across inbox and done."""
    # Check inbox
    inbox_path = INBOX / cert_id
    if inbox_path.is_dir():
        return inbox_path

    # Check done
    if DONE.exists():
        for category_dir in DONE.iterdir():
            if not category_dir.is_dir():
                continue
            for post_dir in category_dir.iterdir():
                if not post_dir.is_dir():
                    continue
                meta = read_metadata(post_dir)
                if meta and meta.get("cert_id") == cert_id:
                    return post_dir
                # Backward compat: folder name = cert_id
                if post_dir.name == cert_id:
                    return post_dir

    return None


# ─── Helpers: LinkedIn token ──────────────────────────────────────────

def load_token() -> dict | None:
    if TOKEN_PATH.exists():
        data = json.loads(TOKEN_PATH.read_text())
        if data.get("expires_at", 0) > time.time():
            return data
    return None


def save_token(data: dict):
    TOKEN_PATH.write_text(json.dumps(data, indent=2))


def post_to_linkedin(post_text: str) -> dict:
    """Post to LinkedIn. Returns {"success": True, "post_id": ...} or {"error": ...}."""
    token = load_token()
    if not token:
        return {"error": "Not connected to LinkedIn"}

    resp = http_requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202601",
        },
        json={
            "author": token["person_urn"],
            "commentary": post_text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
    )

    if resp.status_code == 201:
        return {"success": True, "post_id": resp.headers.get("x-restli-id", "")}
    return {"error": f"LinkedIn API error ({resp.status_code}): {resp.text}"}


# ─── Helpers: move cert to done ───────────────────────────────────────

def move_to_done(cert_id: str, meta: dict):
    """Move a cert from inbox/{cert_id}/ to done/{category}/{short_name}/."""
    src = INBOX / cert_id
    if not src.is_dir():
        return

    category = meta.get("category", "other")
    if category not in CATEGORIES:
        category = "other"
    short_name = meta.get("short_name", cert_id)

    dest = DONE / category / short_name
    dest.mkdir(parents=True, exist_ok=True)

    # Move all files
    for f in src.iterdir():
        shutil.move(str(f), str(dest / f.name))

    # Write post.md for backward compat
    if meta.get("post_text"):
        (dest / "post.md").write_text(meta["post_text"])

    # Update metadata in new location
    write_metadata(dest, meta)

    # Remove empty inbox folder
    if src.exists():
        shutil.rmtree(str(src))


# ─── Routes: Dashboard ────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", linkedin_connected=load_token() is not None)


@app.route("/certs")
def list_certs():
    """All certs across all states."""
    certs = get_all_certs()
    return jsonify({
        "certs": certs,
        "generation": {
            "running": generation_progress["running"],
            "current": generation_progress["current"],
            "total": generation_progress["total"],
            "current_name": generation_progress["current_name"],
        },
    })


@app.route("/cert/<cert_id>")
def get_cert(cert_id):
    folder = find_cert_folder(cert_id)
    if not folder:
        return jsonify({"error": "Not found"}), 404
    meta = read_metadata(folder)
    if not meta:
        return jsonify({"error": "No metadata"}), 404
    return jsonify(meta)


# ─── Routes: Upload ──────────────────────────────────────────────────

@app.route("/upload", methods=["POST"])
def upload_certs():
    """Accept multiple cert files. Create inbox/{cert_id}/ for each."""
    files = request.files.getlist("certs")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400

    uploaded = []
    rejected = []

    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in SUPPORTED:
            rejected.append(f.filename)
            continue

        cert_id = new_cert_id()
        folder = INBOX / cert_id
        folder.mkdir(parents=True, exist_ok=True)

        # Save cert file with original extension
        cert_path = folder / f"cert{ext}"
        f.save(str(cert_path))

        # Write initial metadata
        meta = make_metadata(cert_id, f.filename)
        write_metadata(folder, meta)

        uploaded.append({"cert_id": cert_id, "filename": f.filename})

    return jsonify({"uploaded": uploaded, "rejected": rejected})


# ─── Routes: Cert Actions ────────────────────────────────────────────

@app.route("/cert/<cert_id>", methods=["PATCH"])
def update_cert(cert_id):
    """Update notes or post_text for a cert."""
    folder = find_cert_folder(cert_id)
    if not folder:
        return jsonify({"error": "Not found"}), 404

    meta = read_metadata(folder)
    if not meta:
        return jsonify({"error": "No metadata"}), 404

    data = request.get_json()
    if "notes" in data:
        meta["notes"] = data["notes"]
    if "post_text" in data:
        meta["post_text"] = data["post_text"]
        meta["char_count"] = len(data["post_text"])
        # Also update post.md if it exists
        post_file = folder / "post.md"
        if post_file.exists():
            post_file.write_text(data["post_text"])

    write_metadata(folder, meta)
    return jsonify(meta)


@app.route("/cert/<cert_id>/generate", methods=["POST"])
def generate_cert(cert_id):
    """Generate post for a single cert."""
    folder = INBOX / cert_id
    if not folder.is_dir():
        return jsonify({"error": "Cert not in inbox"}), 404

    meta = read_metadata(folder)
    if not meta:
        return jsonify({"error": "No metadata"}), 404

    cert_file = find_cert_file(folder)
    if not cert_file:
        return jsonify({"error": "No cert file found"}), 404

    meta["status"] = "generating"
    meta["last_error"] = None
    write_metadata(folder, meta)

    try:
        last_shapes = read_last_shapes()
        post_text, llm_meta = generate(cert_file, meta.get("notes"), "default", last_shapes)

        shape_used = llm_meta.get("shape_used", "")
        if shape_used:
            write_last_shape(shape_used)

        meta["status"] = "generated"
        meta["generated_at"] = now_iso()
        meta["post_text"] = post_text
        meta["category"] = llm_meta.get("category", "other")
        meta["short_name"] = llm_meta.get("short_name", cert_id)
        meta["confidence"] = llm_meta.get("confidence", "medium")
        meta["flag_reason"] = llm_meta.get("flag_reason", "")
        meta["shape_used"] = shape_used
        meta["char_count"] = len(post_text)

        # Also write post.md
        (folder / "post.md").write_text(post_text)
        write_metadata(folder, meta)

        return jsonify(meta)
    except Exception as e:
        meta["status"] = "uploaded"
        meta["last_error"] = str(e)
        write_metadata(folder, meta)
        return jsonify({"error": str(e)}), 500


@app.route("/generate-all", methods=["POST"])
def generate_all():
    """Sequential background generation for all uploaded certs."""
    if not generation_lock.acquire(blocking=False):
        return jsonify({"error": "Generation already in progress"}), 409

    # Find all uploaded certs
    uploaded = []
    if INBOX.exists():
        for folder in sorted(INBOX.iterdir()):
            if not folder.is_dir():
                continue
            meta = read_metadata(folder)
            if meta and meta.get("status") == "uploaded":
                uploaded.append((folder, meta))

    if not uploaded:
        generation_lock.release()
        return jsonify({"error": "No uploaded certs to generate"}), 400

    generation_progress["running"] = True
    generation_progress["current"] = 0
    generation_progress["total"] = len(uploaded)

    def run():
        try:
            for i, (folder, meta) in enumerate(uploaded):
                generation_progress["current"] = i + 1
                generation_progress["current_name"] = meta.get("original_filename", "")

                cert_file = find_cert_file(folder)
                if not cert_file:
                    meta["last_error"] = "No cert file found"
                    write_metadata(folder, meta)
                    continue

                meta["status"] = "generating"
                meta["last_error"] = None
                write_metadata(folder, meta)

                try:
                    last_shapes = read_last_shapes()
                    post_text, llm_meta = generate(
                        cert_file, meta.get("notes"), "default", last_shapes
                    )

                    shape_used = llm_meta.get("shape_used", "")
                    if shape_used:
                        write_last_shape(shape_used)

                    meta["status"] = "generated"
                    meta["generated_at"] = now_iso()
                    meta["post_text"] = post_text
                    meta["category"] = llm_meta.get("category", "other")
                    meta["short_name"] = llm_meta.get("short_name", meta["cert_id"])
                    meta["confidence"] = llm_meta.get("confidence", "medium")
                    meta["flag_reason"] = llm_meta.get("flag_reason", "")
                    meta["shape_used"] = shape_used
                    meta["char_count"] = len(post_text)

                    (folder / "post.md").write_text(post_text)
                    write_metadata(folder, meta)
                except Exception as e:
                    meta["status"] = "uploaded"
                    meta["last_error"] = str(e)
                    write_metadata(folder, meta)
        finally:
            generation_progress["running"] = False
            generation_progress["current"] = 0
            generation_progress["total"] = 0
            generation_progress["current_name"] = ""
            generation_lock.release()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"started": True, "total": len(uploaded)})


@app.route("/cert/<cert_id>/save", methods=["POST"])
def save_cert(cert_id):
    """Move cert from inbox to done/."""
    folder = INBOX / cert_id
    if not folder.is_dir():
        return jsonify({"error": "Cert not in inbox"}), 404

    meta = read_metadata(folder)
    if not meta:
        return jsonify({"error": "No metadata"}), 404
    if not meta.get("post_text"):
        return jsonify({"error": "No post generated yet"}), 400

    meta["status"] = "saved"
    meta["saved_at"] = now_iso()
    move_to_done(cert_id, meta)

    return jsonify({"saved": True})


@app.route("/cert/<cert_id>/publish", methods=["POST"])
def publish_cert(cert_id):
    """Post to LinkedIn and save."""
    folder = find_cert_folder(cert_id)
    if not folder:
        return jsonify({"error": "Not found"}), 404

    meta = read_metadata(folder)
    if not meta:
        return jsonify({"error": "No metadata"}), 404
    if not meta.get("post_text"):
        return jsonify({"error": "No post to publish"}), 400

    # Post to LinkedIn
    result = post_to_linkedin(meta["post_text"])
    if "error" in result:
        return jsonify(result), 400

    meta["status"] = "published"
    meta["published_at"] = now_iso()
    meta["linkedin_post_id"] = result.get("post_id", "")

    # If still in inbox, move to done
    if (INBOX / cert_id).is_dir():
        meta["saved_at"] = now_iso()
        move_to_done(cert_id, meta)
    else:
        write_metadata(folder, meta)

    return jsonify({"published": True, "post_id": result.get("post_id", "")})


@app.route("/cert/<cert_id>/regenerate", methods=["POST"])
def regenerate_cert(cert_id):
    """Reset a cert to uploaded state for re-generation."""
    folder = find_cert_folder(cert_id)
    if not folder:
        return jsonify({"error": "Not found"}), 404

    meta = read_metadata(folder)
    if not meta:
        return jsonify({"error": "No metadata"}), 404

    # If in done/, move back to inbox
    if not str(folder).startswith(str(INBOX)):
        new_folder = INBOX / cert_id
        new_folder.mkdir(parents=True, exist_ok=True)
        for f in folder.iterdir():
            shutil.move(str(f), str(new_folder / f.name))
        shutil.rmtree(str(folder))
        folder = new_folder

    # Reset metadata
    meta["status"] = "uploaded"
    meta["generated_at"] = None
    meta["post_text"] = None
    meta["category"] = None
    meta["short_name"] = None
    meta["confidence"] = None
    meta["flag_reason"] = None
    meta["shape_used"] = None
    meta["char_count"] = None
    meta["saved_at"] = None
    meta["published_at"] = None
    meta["linkedin_post_id"] = None
    meta["last_error"] = None

    # Remove post.md
    post_file = folder / "post.md"
    if post_file.exists():
        post_file.unlink()

    write_metadata(folder, meta)
    return jsonify(meta)


@app.route("/cert/<cert_id>", methods=["DELETE"])
def delete_cert(cert_id):
    """Delete a cert and its folder."""
    folder = find_cert_folder(cert_id)
    if not folder:
        return jsonify({"error": "Not found"}), 404

    shutil.rmtree(str(folder))
    return jsonify({"deleted": True})


# ─── Routes: LinkedIn OAuth ──────────────────────────────────────────

@app.route("/linkedin/auth")
def linkedin_auth():
    if not LINKEDIN_CLIENT_ID:
        return jsonify({"error": "LINKEDIN_CLIENT_ID not set in .env"}), 400

    state = secrets.token_hex(16)
    session["linkedin_state"] = state

    auth_url = (
        "https://www.linkedin.com/oauth/v2/authorization?"
        f"response_type=code&"
        f"client_id={LINKEDIN_CLIENT_ID}&"
        f"redirect_uri={LINKEDIN_REDIRECT_URI}&"
        f"scope={LINKEDIN_SCOPES.replace(' ', '%20')}&"
        f"state={state}"
    )
    return redirect(auth_url)


@app.route("/linkedin/callback")
def linkedin_callback():
    error = request.args.get("error")
    if error:
        return render_template("index.html",
            linkedin_connected=False,
            error=f"LinkedIn auth failed: {request.args.get('error_description', error)}")

    code = request.args.get("code")
    state = request.args.get("state")

    if state != session.get("linkedin_state"):
        return render_template("index.html",
            linkedin_connected=False,
            error="OAuth state mismatch. Try again.")

    token_resp = http_requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if token_resp.status_code != 200:
        return render_template("index.html",
            linkedin_connected=False,
            error=f"Token exchange failed: {token_resp.text}")

    token_data = token_resp.json()
    access_token = token_data["access_token"]
    expires_in = token_data.get("expires_in", 5184000)

    userinfo_resp = http_requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if userinfo_resp.status_code != 200:
        return render_template("index.html",
            linkedin_connected=False,
            error=f"Failed to get user info: {userinfo_resp.text}")

    userinfo = userinfo_resp.json()
    person_id = userinfo.get("sub", "")
    name = userinfo.get("name", "")

    save_token({
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
        "person_urn": f"urn:li:person:{person_id}",
        "name": name,
    })

    return render_template("index.html",
        linkedin_connected=True,
        success=f"Connected as {name}!")


@app.route("/linkedin/status")
def linkedin_status():
    token = load_token()
    if token:
        days_left = max(0, int((token["expires_at"] - time.time()) / 86400))
        return jsonify({
            "connected": True,
            "name": token.get("name", ""),
            "days_left": days_left,
        })
    return jsonify({"connected": False})


# ─── Main ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    INBOX.mkdir(exist_ok=True)
    DONE.mkdir(exist_ok=True)
    print("\n  Med Portfolio — http://localhost:5051\n")
    app.run(debug=True, port=5051)
