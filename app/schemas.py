from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChannelPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    channel_number: int | None = Field(default=None, ge=1, le=1000000)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    tvg_name: str | None = Field(default=None, max_length=300)
    epg_id: str | None = Field(default=None, max_length=300)
    group_title: str | None = Field(default=None, min_length=1, max_length=100)
    is_enabled: bool | None = None

    @field_validator('name', 'group_title', 'tvg_name', 'epg_id')
    @classmethod
    def clean(cls, value):
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError('Use non-empty text without control characters')
        return value.strip() if value else value

    @field_validator('channel_number', 'name', 'group_title', 'is_enabled')
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError('This field cannot be null')
        return value


class SyncRequest(BaseModel):
    countries: list[str] | None = None
    categories: list[str] | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class SetupRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(default='admin', min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=200)
    confirm: str = Field(min_length=1, max_length=200)

    @field_validator('confirm')
    @classmethod
    def match(cls, value, info):
        if value != info.data.get('password'):
            raise ValueError('Passwords do not match')
        return value


class JellyfinConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(default='', max_length=200)
    base_url: str = Field(min_length=1, max_length=500)
    auto_sync: bool = False

    @field_validator('url', 'base_url')
    @classmethod
    def http_url(cls, value):
        if not value.strip().lower().startswith(('http://', 'https://')):
            raise ValueError('Must be an http(s) URL')
        return value.strip().rstrip('/')
