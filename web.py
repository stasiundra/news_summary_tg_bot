import hmac
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

import config
import database
import summarizer

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

SESSION_COOKIE = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 дней

_signer = URLSafeSerializer(config.WEB_AUTH_TOKEN or "insecure-dev-key")


def _set_session_cookie(response: Response) -> None:
    token = _signer.dumps({"ts": int(time.time())})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=False,  # loopback / reverse-proxy; set True behind TLS
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


async def require_auth(request: Request) -> None:
    """Dependency: validate signed session cookie. Redirect to /login if invalid."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _redirect_login()
    try:
        _signer.loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise _redirect_login()


def _redirect_login() -> RedirectResponse:
    return RedirectResponse(url="/login", status_code=303)


@app.on_event("startup")
async def startup():
    await database.init_db()


def fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")


templates.env.filters["fmt_date"] = fmt_date


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if config.WEB_AUTH_TOKEN and hmac.compare_digest(password, config.WEB_AUTH_TOKEN):
        response = RedirectResponse(url="/", status_code=303)
        _set_session_cookie(response)
        return response
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": "Неверный пароль",
    })


@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    _clear_session_cookie(response)
    return response


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def digest_page(request: Request):
    return templates.TemplateResponse("digest.html", {"request": request})


@app.post("/digest", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def digest_generate(request: Request, period: str = Form(...)):
    hours = 24 if period == "24h" else 168
    label = "сутки" if period == "24h" else "неделю"
    since_ts = int(time.time()) - hours * 3600
    posts = await database.get_posts_since(since_ts)
    result = await summarizer.generate_digest(posts, label)
    return templates.TemplateResponse("digest.html", {
        "request": request,
        "digest": result,
        "period": period,
    })


@app.post("/ask", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def ask_question(
    request: Request,
    question: str = Form(...),
    period: str = Form(...),
    digest_text: str = Form(""),
):
    hours = 24 if period == "24h" else 168
    since_ts = int(time.time()) - hours * 3600
    posts = await database.get_posts_since(since_ts)
    answer = await summarizer.answer_question(posts, question)
    return templates.TemplateResponse("digest.html", {
        "request": request,
        "digest": digest_text,
        "period": period,
        "question": question,
        "answer": answer,
    })


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

@app.get("/channels", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def channels_page(request: Request, msg: str = ""):
    channels = await database.get_active_channels()
    return templates.TemplateResponse("channels.html", {
        "request": request,
        "channels": channels,
        "msg": msg,
    })


@app.post("/channels/add", dependencies=[Depends(require_auth)])
async def channel_add(username: str = Form(...)):
    username = username.strip().lstrip("@")
    if username:
        await database.add_channel(username, username)
    return RedirectResponse(url=f"/channels?msg=Канал+@{username}+добавлен", status_code=303)


@app.post("/channels/remove", dependencies=[Depends(require_auth)])
async def channel_remove(username: str = Form(...)):
    await database.remove_channel(username)
    return RedirectResponse(url=f"/channels?msg=Канал+@{username}+удалён", status_code=303)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.get("/users", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
async def users_page(request: Request, msg: str = ""):
    users = await database.get_active_users()
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
        "msg": msg,
    })


@app.post("/users/remove", dependencies=[Depends(require_auth)])
async def user_remove(user_id: int = Form(...)):
    await database.remove_user(user_id)
    return RedirectResponse(url="/users?msg=Пользователь+удалён", status_code=303)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("web:app", host=config.WEB_BIND_HOST, port=config.WEB_PORT, reload=False)