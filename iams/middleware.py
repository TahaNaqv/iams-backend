import contextvars
import uuid

request_id_ctx = contextvars.ContextVar("request_id", default="-")


def get_current_request_id() -> str:
    """Return the request_id for the current async/thread context, or '-' outside requests."""
    return request_id_ctx.get()


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        request_id_ctx.reset(token)
        return response


class RequestIdLoggingFilter:
    def filter(self, record):
        record.request_id = request_id_ctx.get()
        return True
