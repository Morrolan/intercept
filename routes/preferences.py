"""Session-only account preferences, separate from global station configuration."""

from flask import Blueprint, jsonify, request, session

from utils.preferences import (
    PER_DEVICE_KEYS,
    PER_DEVICE_PREFIXES,
    SYNCED_KEYS,
    get_preferences,
    put_preferences,
    user_id,
)

preferences_bp = Blueprint('preferences', __name__)


def current_account():
    if not session.get('logged_in') or not session.get('username'):
        return None
    return user_id(session['username'])


@preferences_bp.app_context_processor
def preferences_context():
    account = current_account()
    return {'account_prefs': {
        'owner': str(account), 'prefs': get_preferences(account),
        'syncedKeys': sorted(SYNCED_KEYS), 'perDeviceKeys': PER_DEVICE_KEYS,
        'perDevicePrefixes': PER_DEVICE_PREFIXES,
    } if account is not None else None}


@preferences_bp.after_app_request
def private_preferences(response):
    # HTML contains account data; never reuse it across sessions or restores.
    if request.blueprint == 'preferences' or response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store'
        response.vary.add('Cookie')
    return response


@preferences_bp.route('/api/me/prefs', methods=['GET', 'PUT'])
def preferences():
    account = current_account()
    if account is None:
        return jsonify(error='Sign in required'), 401
    if request.method == 'PUT':
        # JSON plus a custom header blocks cross-origin simple requests even
        # without flask-wtf; explicitly reject foreign origins/fetch metadata.
        if (not request.is_json or request.headers.get('X-Intercept-Prefs') != '1'
                or request.headers.get('X-Intercept-Prefs-Owner') != str(account)
                or request.headers.get('Sec-Fetch-Site') == 'cross-site'
                or (request.headers.get('Origin') is not None
                    and request.headers['Origin'].rstrip('/') != request.host_url.rstrip('/'))):
            return jsonify(error='Same-origin JSON request required'), 403
        if request.content_length and request.content_length > 4 * 1024 * 1024:
            return jsonify(error='Request too large'), 413
        try:
            put_preferences(account, request.get_json(), import_only=request.args.get('import') == '1')
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    return jsonify(prefs=get_preferences(account))
