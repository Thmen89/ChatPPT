from typing import Optional

from pydantic import BaseModel, computed_field
import uuid


class PresentationAndPath(BaseModel):
    presentation_id: uuid.UUID
    path: str


class PresentationPathAndEditPath(PresentationAndPath):
    edit_path: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def download_url(self) -> Optional[str]:
        """Signed, short-lived link to the exported file (``auth.signed_url_minutes``);
        works without an auth header, so it can be handed on (webhooks, chat bots)."""
        from chatppt.auth.web import download_url

        try:
            return download_url(self.path)
        except Exception:  # never fail a finished generation over a link
            return None
