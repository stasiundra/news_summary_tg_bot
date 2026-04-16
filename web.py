import time
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import database
import summarizer

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
async def startup():
    await database.init_db()


def fmt_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y")


templates.env.filters["fmt_date"] = fmt_date


# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def digest_page(request: Request):
    return templates.TemplateResponse("digest.html", {"request": request})


@app.post("/digest", response_class=HTMLResponse)
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


@app.post("/ask", response_class=HTMLResponse)
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

@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request, msg: str = ""):
    channels = await database.get_active_channels()
    return templates.TemplateResponse("channels.html", {
        "request": request,
        "channels": channels,
        "msg": msg,
    })


@app.post("/channels/add")
async def channel_add(username: str = Form(...)):
    username = username.strip().lstrip("@")
    if username:
        await database.add_channel(username, username)
    return RedirectResponse(url=f"/channels?msg=Канал+@{username}+добавлен", status_code=303)


@app.post("/channels/remove")
async def channel_remove(username: str = Form(...)):
    await database.remove_channel(username)
    return RedirectResponse(url=f"/channels?msg=Канал+@{username}+удалён", status_code=303)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, msg: str = ""):
    users = await database.get_active_users()
    return templates.TemplateResponse("users.html", {
        "request": request,
        "users": users,
        "msg": msg,
    })


@app.post("/users/remove")
async def user_remove(user_id: int = Form(...)):
    await database.remove_user(user_id)
    return RedirectResponse(url="/users?msg=Пользователь+удалён", status_code=303)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("web:app", host="0.0.0.0", port=8080, reload=False)
