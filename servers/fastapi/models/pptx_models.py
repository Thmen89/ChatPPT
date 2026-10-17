"""What the exporter sends to the PPTX writer: a deck as positioned shapes.

Sizes are CSS pixels of a 1280x720 slide; the writer turns them into points (x 0.75).
The schema is the one the earlier bundled converter read, so either side can be swapped.
"""

from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR_TYPE
from pptx.enum.text import MSO_VERTICAL_ANCHOR, PP_ALIGN
from pptx.util import Length, Pt


def px_to_pt(px: float) -> float:
    return float(px) * 0.75


class PptxBoxShapeEnum(Enum):
    RECTANGLE = "rectangle"
    CIRCLE = "circle"


class PptxObjectFitEnum(Enum):
    CONTAIN = "contain"
    COVER = "cover"
    FILL = "fill"


class PptxSpacingModel(BaseModel):
    top: float = 0
    bottom: float = 0
    left: float = 0
    right: float = 0


class PptxPositionModel(BaseModel):
    left: float = 0
    top: float = 0
    width: float = 0
    height: float = 0

    def to_pt_list(self) -> List[Length]:
        return [Pt(px_to_pt(v)) for v in (self.left, self.top, self.width, self.height)]

    def to_pt_xyxy(self) -> List[Length]:
        edges = (self.left, self.top, self.left + self.width, self.top + self.height)
        return [Pt(px_to_pt(v)) for v in edges]


class PptxFontModel(BaseModel):
    name: str = "Inter"
    size: float = 16
    italic: bool = False
    color: str = "000000"
    font_weight: Optional[int] = 400
    underline: Optional[bool] = None
    strike: Optional[bool] = None


class PptxFillModel(BaseModel):
    color: str
    opacity: float = 1.0


class PptxStrokeModel(BaseModel):
    color: str
    thickness: float
    opacity: float = 1.0


class PptxShadowModel(BaseModel):
    radius: float
    offset: float = 0
    color: str = "000000"
    opacity: float = 0.5
    angle: float = 0


class PptxTextRunModel(BaseModel):
    text: str
    font: Optional[PptxFontModel] = None


class PptxParagraphBulletModel(BaseModel):
    type: Literal["default", "number"]
    color: Optional[str] = None


class PptxParagraphModel(BaseModel):
    spacing: Optional[PptxSpacingModel] = None
    alignment: Optional[PP_ALIGN] = None
    font: Optional[PptxFontModel] = None
    line_height: Optional[float] = None
    letter_spacing: Optional[float] = None
    level: Optional[int] = None
    bullet: Optional[PptxParagraphBulletModel] = None
    text: Optional[str] = None
    text_runs: Optional[List[PptxTextRunModel]] = None


class PptxObjectFitModel(BaseModel):
    fit: Optional[PptxObjectFitEnum] = None
    focus: Optional[Annotated[List[Optional[float]], Field(min_length=2, max_length=2)]] = None

    @field_validator("fit", mode="before")
    @classmethod
    def _other_fits_stretch(cls, value: object) -> object:
        # CSS also has none / scale-down; those stretch to the box rather than fail the export.
        known = {member.value for member in PptxObjectFitEnum}
        return value if value is None or isinstance(value, PptxObjectFitEnum) or value in known else None


class PptxPictureModel(BaseModel):
    is_network: bool = False
    path: str


class PptxTextBoxModel(BaseModel):
    shape_type: Literal["textbox"] = "textbox"
    margin: Optional[PptxSpacingModel] = None
    fill: Optional[PptxFillModel] = None
    stroke: Optional[PptxStrokeModel] = None
    shadow: Optional[PptxShadowModel] = None
    position: PptxPositionModel
    rotation: Optional[float] = None
    text_wrap: bool = True
    vertical_alignment: Optional[MSO_VERTICAL_ANCHOR] = None
    paragraphs: List[PptxParagraphModel]


class PptxAutoShapeBoxModel(BaseModel):
    shape_type: Literal["autoshape"] = "autoshape"
    type: MSO_AUTO_SHAPE_TYPE = MSO_AUTO_SHAPE_TYPE.RECTANGLE
    margin: Optional[PptxSpacingModel] = None
    fill: Optional[PptxFillModel] = None
    stroke: Optional[PptxStrokeModel] = None
    shadow: Optional[PptxShadowModel] = None
    position: PptxPositionModel
    rotation: Optional[float] = None
    text_wrap: bool = True
    border_radius: Optional[float] = None
    paragraphs: Optional[List[PptxParagraphModel]] = None


class PptxPictureBoxModel(BaseModel):
    shape_type: Literal["picture"] = "picture"
    position: PptxPositionModel
    rotation: Optional[float] = None
    margin: Optional[PptxSpacingModel] = None
    clip: bool = True
    opacity: Optional[float] = None
    invert: bool = False
    border_radius: Optional[List[float]] = None
    shape: Optional[PptxBoxShapeEnum] = None
    object_fit: Optional[PptxObjectFitModel] = None
    picture: PptxPictureModel


class PptxConnectorModel(BaseModel):
    shape_type: Literal["connector"] = "connector"
    type: MSO_CONNECTOR_TYPE = MSO_CONNECTOR_TYPE.STRAIGHT
    position: PptxPositionModel
    rotation: Optional[float] = None
    thickness: float = 0.5
    color: str = "000000"
    opacity: float = 1.0


PptxShape = Annotated[
    Union[PptxTextBoxModel, PptxAutoShapeBoxModel, PptxConnectorModel, PptxPictureBoxModel],
    Field(discriminator="shape_type"),
]


class PptxSlideModel(BaseModel):
    background: Optional[PptxFillModel] = None
    note: Optional[str] = None
    shapes: List[PptxShape]


class PptxPresentationModel(BaseModel):
    name: Optional[str] = None
    slides: List[PptxSlideModel]
