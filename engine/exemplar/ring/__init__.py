"""Stream A - Ring integration. Server-side only (the Ring API blocks browser CORS).

    from exemplar.ring import AuthManager, RingClient

    auth = AuthManager.from_settings(store)          # store: TokenStore backed by the ring_auth table
    async with RingClient(auth) as ring:
        for dev in await ring.list_devices(): ...
        async for ev in ring.history(dev.id): ...
        clip = await ring.download_event_video(ev)   # 303 -> pre-signed GET, 416/425 backoff built in
"""
from .client import (
    MediaResult,
    RetryPolicy,
    RingClient,
    RingDevice,
    RingEvent,
    RingUser,
)
from .errors import (
    CorruptRecordingError,
    UnprocessableMediaError,
    FeatureDisabledError,
    InvalidPayloadError,
    IPBlockedError,
    MediaNotFoundError,
    NotFoundError,
    RateLimitedError,
    RecordingNotReadyError,
    RingAuthError,
    RingError,
    RingForbiddenError,
    RingTransportError,
    ServerError,
    TimeRangeNotAuthorizedError,
)
from .tokens import (
    API_BASE,
    AuthManager,
    AuthStatus,
    AuthorizeRequest,
    InMemoryTokenStore,
    OAuthApp,
    OAuthTokens,
    PlaygroundToken,
    StoredAuth,
    TokenProvider,
    TokenStore,
    compute_nonce,
    decode_jwt_claims,
    generate_pkce,
    nonce_matches,
)
from .webhook import (
    Delivery,
    InMemoryDeduper,
    WebhookDeduper,
    WebhookEvent,
    parse_webhook,
    process_delivery,
    sign_body,
    verify_signature,
)

__all__ = [n for n in dir() if not n.startswith("_")]
