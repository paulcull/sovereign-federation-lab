"""Typed system and experience command contracts for clients and OpenAPI."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)
    display_name: str = Field(min_length=10, max_length=120, pattern=r'^Synthetic ')
    party_type: Literal['PERSON', 'ORGANISATION']
    identity_profile: Literal['owner_only', 'global_minimum', 'global_minimum_no_us'] = 'owner_only'


class RelationshipInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    sharing_profile: Literal['owner_only', 'uk_servicing_no_us'] = 'owner_only'
    email: str = Field(max_length=254, pattern=r'@example\.invalid$')


class BusinessCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_version: int = Field(ge=1, strict=True)
    command: Literal['update_contact', 'withdraw_consent', 'restore_consent']
    value: str | None = Field(default=None, max_length=254)
