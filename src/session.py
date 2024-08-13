import litestar


@litestar.get("/session", sync_to_thread=False)
def check_session_handler(request: litestar.Request) -> dict[str, bool]:
    return {"has_session": request.session != {}}


@litestar.post("/session", sync_to_thread=False)
def create_session_handler(request: litestar.Request) -> None:
    request_hash = dir(request)
    
    if not request.session:
        request.set_session({"username": "moishezuchmir"})


@litestar.delete("/session", sync_to_thread=False)
def delete_session_handler(request: litestar.Request) -> None:
    if request.session:
        request.clear_session()
