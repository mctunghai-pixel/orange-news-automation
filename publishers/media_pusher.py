"""Push images to the media-public orphan branch via git worktree.

Returns a map of {local_path: raw.githubusercontent.com URL} that the
Instagram publisher feeds into the Graph API as image_url.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

GITHUB_OWNER = "mctunghai-pixel"
GITHUB_REPO = "orange-news-automation"
MEDIA_BRANCH = "media-public"
RAW_URL_TEMPLATE = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
    f"{MEDIA_BRANCH}/{{filename}}"
)


def _log(msg: str) -> None:
    print(f"[media_pusher] {msg}", file=sys.stderr)


def _run(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(cmd)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.strip()


def _discover_repo_root() -> str:
    cwd = os.getcwd()
    return _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd)


def push_images_to_media_branch(
    image_paths: list[str],
    date_str: str,
    *,
    repo_root: str | None = None,
) -> dict[str, str]:
    if not image_paths:
        _log("no images supplied — skipping push")
        return {}

    repo_root = repo_root or _discover_repo_root()

    missing = [p for p in image_paths if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError(f"missing image files: {missing}")

    try:
        _run(
            ["git", "rev-parse", "--verify", f"origin/{MEDIA_BRANCH}"],
            cwd=repo_root,
        )
    except RuntimeError as e:
        raise RuntimeError(
            f"origin/{MEDIA_BRANCH} not found. Push the orphan branch first: "
            f"git push -u origin {MEDIA_BRANCH}"
        ) from e

    worktree_dir = tempfile.mkdtemp(prefix="orange-news-mp-")
    url_map: dict[str, str] = {}

    try:
        _run(
            ["git", "worktree", "add", worktree_dir, MEDIA_BRANCH],
            cwd=repo_root,
        )
        _run(["git", "pull", "--ff-only", "origin", MEDIA_BRANCH], cwd=worktree_dir)

        copied_filenames: list[str] = []
        for src in image_paths:
            filename = os.path.basename(src)
            dest = os.path.join(worktree_dir, filename)
            shutil.copy2(src, dest)
            copied_filenames.append(filename)
            url_map[src] = RAW_URL_TEMPLATE.format(filename=filename)

        _run(["git", "add", "--"] + copied_filenames, cwd=worktree_dir)

        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=worktree_dir,
        )
        if diff.returncode == 0:
            _log("no content changes — skipping commit/push, returning URL map")
            return url_map

        msg_file = os.path.join(worktree_dir, ".commit_msg")
        with open(msg_file, "w") as f:
            f.write(
                f"media: publish {len(copied_filenames)} image(s) for {date_str}\n\n"
                f"Co-Authored-By: Claude <noreply@anthropic.com>\n"
            )
        _run(["git", "commit", "-F", msg_file], cwd=worktree_dir)
        os.unlink(msg_file)

        _run(["git", "push", "origin", MEDIA_BRANCH], cwd=worktree_dir)
        _log(f"pushed {len(copied_filenames)} image(s) to {MEDIA_BRANCH}")

        return url_map
    finally:
        try:
            _run(
                ["git", "worktree", "remove", "--force", worktree_dir],
                cwd=repo_root,
            )
        except Exception as cleanup_err:
            _log(f"worktree cleanup warning: {cleanup_err}")
            shutil.rmtree(worktree_dir, ignore_errors=True)
