"""Shared, bounded contract for Chief and local creative agents."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from chief_flyer_direction import ReferenceInput


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class DesignRequest(Strict):
    goal: str = Field(min_length=3, max_length=4000)
    exact_copy: list[str] = Field(default_factory=list, max_length=16)
    reference_inputs: list[ReferenceInput] = Field(default_factory=list, max_length=4)
    size: Literal['1024x1024', '1024x1536', '1536x1024'] = '1024x1536'
    quality: Literal['low', 'medium', 'high'] = 'high'


class Placement(Strict):
    image_id: UUID
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)


class Plan(Strict):
    concept: str = Field(min_length=3, max_length=900)
    reference_analysis: str = Field(min_length=3, max_length=1600)
    typography: str = Field(min_length=3, max_length=900)
    composition: str = Field(min_length=3, max_length=1200)
    palette: str = Field(min_length=3, max_length=500)
    materials_light: str = Field(min_length=3, max_length=800)
    preserve: str = Field(default='', max_length=900)
    avoid: str = Field(default='', max_length=900)
    # The planner writes only art direction. Approved copy is supplied separately
    # by the server and cannot be rewritten/expanded by this schema.
    placements: list[Placement] = Field(default_factory=list, max_length=4)
    copy_concerns: list[str] = Field(default_factory=list, max_length=5)


class Review(Strict):
    observed_text: str = Field(max_length=4000)
    reference_match: bool
    readable: bool
    composition_coherent: bool
    brand_assets_clean: bool
    issues: list[str] = Field(default_factory=list, max_length=8)
    repair_instruction: str = Field(default='', max_length=1500)


WORKFLOW = '''
CREATIVE DIRECTOR WORKFLOW:
People describe goals and supply inspiration; do not require expert design prompts.
Read actual reference pixels. Identify hierarchy, type proportions, spacing, density,
materials, lighting, depth and what the owner explicitly wants to borrow. Latest requests
override older styles. Keep reference company names/offers out of this business's copy.
Use original logo/product pixels as protected composition layers, not generated substitutes.
Never turn "negative space" into a white placeholder rectangle. Preserve transparency.
Choose image generation for textured/dimensional artwork; finish protected assets separately.
Keep verified offer facts and approved visible copy separate from creative instructions.
Inspect the rendered image, including reference fidelity, readable copy and asset treatment.
Repair specific defects once within the approved generation allowance; never rerun an
uncertain provider request. A generated file is not an owner-approved or published design.
Remember design preferences only through the owner's explicit Remember this style control.
'''

CHIEF_PROMPT = WORKFLOW + '''
For flyer/poster/social-image creation or revision, call design_flyer. Supply the user's
goal in plain language, a concise exact_copy list sourced from owner input or verified
facts, and explicit reference roles. The Creative Director performs the detailed visual
analysis, production planning, generation, protected-asset composition and review.
You do not need to write a long image prompt or a layer-by-layer layout. Classify the
official logo as logo, actual UI as product, inspiration as style and revision as edit_target.
Do not select a failed earlier design as edit_target when the owner wants a fresh direction.
If approved copy already exists, preserve it except for the owner's requested edits.
If an essential offer fact is missing/conflicting, ask one factual question instead.
The action allows at most two image renders (initial plus one quality repair), plus
planning/review calls. It creates a private draft only, using existing permission settings.
'''
