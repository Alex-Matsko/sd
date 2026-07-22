from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.core.enums import Channel
from app.db import get_db
from app.models.user import User
from app.schemas.integration_setting import IntegrationSettingRead, IntegrationSettingUpdate
from app.services import integration_settings as settings_service

router = APIRouter(prefix="/settings/integrations", tags=["integration-settings"])

# Channels with an external system to configure. Portal/WhatsApp are excluded:
# the portal has no separate connection settings yet, WhatsApp is reserved but
# unimplemented (section 13, вне объёма v1).
CONFIGURABLE_CHANNELS = [Channel.EMAIL, Channel.TELEGRAM, Channel.MAX, Channel.PHONE]


@router.get("", response_model=list[IntegrationSettingRead])
def list_integration_settings(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[IntegrationSettingRead]:
    return [settings_service.to_read(settings_service.get_or_create(db, ch)) for ch in CONFIGURABLE_CHANNELS]


@router.get("/{channel}", response_model=IntegrationSettingRead)
def get_integration_setting(
    channel: Channel, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> IntegrationSettingRead:
    return settings_service.to_read(settings_service.get_or_create(db, channel))


@router.put("/{channel}", response_model=IntegrationSettingRead)
def update_integration_setting(
    channel: Channel,
    payload: IntegrationSettingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> IntegrationSettingRead:
    setting = settings_service.upsert(db, channel, payload)
    return settings_service.to_read(setting)
