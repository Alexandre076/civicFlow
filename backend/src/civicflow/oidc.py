"""Pinned Google discovery and Authlib validation; injectable HTTP for offline tests."""

import time
from urllib.parse import urlencode, urlsplit

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from authlib.jose import JsonWebToken
from authlib.oidc.core import CodeIDToken

ISSUER = "https://accounts.google.com"
DISCOVERY = ISSUER + "/.well-known/openid-configuration"


class InvalidToken(Exception):
    pass


class ProviderUnavailable(Exception):
    pass


class GoogleOIDC:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def metadata(self):
        try:
            with httpx.Client(transport=self.transport, timeout=10) as client:
                response = client.get(DISCOVERY)
                response.raise_for_status()
                data = response.json()
            if data["issuer"] != ISSUER:
                raise ValueError("issuer")
            # Provider metadata is trusted only over HTTPS, never browser supplied.
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                url = urlsplit(data[key])
                if url.scheme != "https" or not url.hostname or url.username:
                    raise ValueError("endpoint")
            return data
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ProviderUnavailable from exc

    def authorization_url(self, state, nonce, challenge):
        data = self.metadata()
        return (
            data["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self.settings.google_client_id,
                    "redirect_uri": self.settings.callback_url,
                    "scope": "openid profile email",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    def exchange(self, code, verifier, nonce):
        data = self.metadata()
        try:
            with OAuth2Client(
                self.settings.google_client_id,
                self.settings.google_client_secret,
                token_endpoint_auth_method="client_secret_post",
                transport=self.transport,
                timeout=10,
            ) as client:
                client.register_compliance_hook(
                    "access_token_response",
                    lambda response: response.raise_for_status(),
                )
                token = client.fetch_token(
                    data["token_endpoint"],
                    code=code,
                    code_verifier=verifier,
                    redirect_uri=self.settings.callback_url,
                    grant_type="authorization_code",
                )
                keys_response = client.request(
                    "GET", data["jwks_uri"], withhold_token=True
                )
                keys_response.raise_for_status()
                keys = keys_response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise ProviderUnavailable from exc
            raise InvalidToken from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        except Exception as exc:
            raise InvalidToken from exc
        return self.validate(token, keys, nonce)

    def validate(self, token, keys, nonce):
        try:
            claims = JsonWebToken(["RS256"]).decode(
                token["id_token"],
                keys,
                claims_cls=CodeIDToken,
                claims_options={
                    "iss": {
                        "essential": True,
                        "values": [ISSUER, "accounts.google.com"],
                    },
                    "aud": {"essential": True, "value": self.settings.google_client_id},
                    "exp": {"essential": True},
                    "iat": {"essential": True},
                    "sub": {"essential": True},
                    "nonce": {"essential": True},
                },
                claims_params={
                    "nonce": nonce,
                    "client_id": self.settings.google_client_id,
                    "access_token": token.get("access_token"),
                },
            )
            claims.validate(leeway=self.settings.clock_skew)
            if (
                not isinstance(claims["sub"], str)
                or not claims["sub"].strip()
                or len(claims["sub"]) > 255
            ):
                raise ValueError("subject")
            if claims["iat"] > time.time() + self.settings.clock_skew:
                raise ValueError("issued at")
            if "azp" in claims and claims["azp"] != self.settings.google_client_id:
                raise ValueError("authorized party")
            return dict(claims)
        except Exception as exc:
            raise InvalidToken from exc
