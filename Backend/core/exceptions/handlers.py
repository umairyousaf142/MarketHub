from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


def custom_exception_handler(exc, context):
    """
    Every API error returns a consistent shape:
    {
        "success": false,
        "error": {
            "code": "...",
            "message": "...",
            "details": {...}   # optional field-level errors
        }
    }
    """
    response = exception_handler(exc, context)

    if response is not None:
        error_payload = {
            'success': False,
            'error': {
                'code':    _get_error_code(response.status_code),
                'message': _extract_message(response.data),
                'details': response.data if isinstance(response.data, dict) else {},
            }
        }
        response.data = error_payload

    return response


def _get_error_code(status_code):
    codes = {
        400: 'BAD_REQUEST',
        401: 'UNAUTHORIZED',
        403: 'FORBIDDEN',
        404: 'NOT_FOUND',
        405: 'METHOD_NOT_ALLOWED',
        409: 'CONFLICT',
        422: 'UNPROCESSABLE_ENTITY',
        429: 'RATE_LIMIT_EXCEEDED',
        500: 'INTERNAL_SERVER_ERROR',
    }
    return codes.get(status_code, 'ERROR')


def _extract_message(data):
    if isinstance(data, dict):
        if 'detail' in data:
            return str(data['detail'])
        first_key = next(iter(data), None)
        if first_key:
            val = data[first_key]
            return str(val[0]) if isinstance(val, list) else str(val)
    if isinstance(data, list) and data:
        return str(data[0])
    return 'An error occurred.'
