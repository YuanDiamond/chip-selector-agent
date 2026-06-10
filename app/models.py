from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class Project(BaseModel):
    id: str
    name: str
    category: str = "board"
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class InventoryPart(BaseModel):
    id: str
    mpn: str
    manufacturer: str
    category: str
    description: str
    package: str
    location: str
    quantity_total: int
    quantity_reserved: int = 0
    unit_price: float = 0
    datasheet_url: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @property
    def quantity_available(self) -> int:
        return max(0, self.quantity_total - self.quantity_reserved)


class Requirement(BaseModel):
    raw_text: str
    category: Optional[str] = None
    vin: Optional[float] = None
    vout: Optional[float] = None
    current: Optional[float] = None
    resolution_bits: Optional[int] = None
    sample_rate_ksps: Optional[float] = None
    channels: Optional[int] = None
    interface: Optional[str] = None
    package: Optional[str] = None
    quantity: int = 1
    priorities: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class KnowledgeChunk(BaseModel):
    id: str
    document_id: str
    part_id: Optional[str] = None
    project_id: Optional[str] = None
    title: str
    page: int
    text: str


class KnowledgeDocument(BaseModel):
    id: str
    filename: str
    part_id: Optional[str] = None
    project_id: Optional[str] = None
    pages: int
    chunks: int


class Candidate(BaseModel):
    source: Literal["lab", "supplier"]
    part: InventoryPart
    score: float = 0
    reasons: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    hard_pass: bool = True


class RecommendationSession(BaseModel):
    id: str
    project_id: str
    requirement: Requirement
    candidates: list[Candidate]
    summary: str


class Reservation(BaseModel):
    id: str
    project_id: str
    part_id: str
    quantity: int
    status: Literal["reserved", "confirmed", "cancelled"] = "reserved"


class StockTransaction(BaseModel):
    id: str
    reservation_id: str
    project_id: str
    part_id: str
    quantity: int
    action: Literal["consume"]


class AgentState(TypedDict, total=False):
    project_id: str
    user_message: str
    intent: str
    requirement: Requirement
    inventory_candidates: list[Candidate]
    supplier_candidates: list[Candidate]
    knowledge_snippets: list[KnowledgeChunk]
    ranked_candidates: list[Candidate]
    summary: str
    # ===== 系统级选型扩展字段 =====
    system_plan: Optional[SystemPlan]
    modules: list[Module]
    bom_entries: list[BOMEntry]
    current_module_index: int
    planning_reasoning: str


# ── 系统架构推导模型 ──────────────────────────────────────────────

class SystemType(StrEnum):
    SENSOR_BOARD = "sensor_board"
    POWER_MANAGEMENT = "power_mgmt"
    DATA_ACQUISITION = "daq"
    MOTOR_CONTROL = "motor_control"
    COMMUNICATION_GATEWAY = "comm_gw"
    AUDIO_ANALYSIS = "audio_analysis"
    SIGNAL_CONDITIONING = "signal_cond"
    GENERAL_EMBEDDED = "general_embedded"
    UNKNOWN = "unknown"


class ModuleType(StrEnum):
    MCU = "mcu"
    POWER_LDO = "ldo"
    POWER_BUCK = "buck"
    ADC = "adc"
    DAC = "dac"
    COMMUNICATION = "comm"
    STORAGE = "storage"
    DRIVER = "driver"
    SENSOR_INTERFACE = "sensor"
    CLOCK = "clock"
    PROTECTION = "protection"
    ANALOG_FILTER = "analog_filter"
    OPAMP = "opamp"
    COMPARATOR = "comparator"
    ISOLATION = "isolation"
    OTHER = "other"


class ResourceBudget(BaseModel):
    io_count: int = 0
    ram_kb: int = 0
    flash_kb: int = 0
    adc_resolution_bits: int = 0
    adc_channels: int = 0
    adc_sample_rate_ksps: float = 0.0
    dac_resolution_bits: int = 0
    dac_channels: int = 0
    dac_update_rate_ksps: float = 0.0
    clock_freq_mhz: float = 0.0
    clock_sources: int = 0
    bandwidth_kbps: int = 0
    vin_min: float = 0.0
    vin_max: float = 0.0
    current_a: float = 0.0
    voltage_rails: dict[str, float] = Field(default_factory=dict)
    timing_constraints: str = ""
    notes: str = ""


class Module(BaseModel):
    id: str
    name: str
    module_type: ModuleType
    rank: int = 99
    requirement: Requirement = Field(default_factory=lambda: Requirement(raw_text=""))
    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)
    quantity: int = 1
    justification: str = ""
    candidates: list[Candidate] = Field(default_factory=list)
    selected_part_id: Optional[str] = None


class SystemPlan(BaseModel):
    id: str = ""
    project_id: str = ""
    system_type: SystemType = SystemType.UNKNOWN
    system_name: str = ""
    user_raw_input: str = ""
    reasoning: str = ""
    assumptions: list[str] = Field(default_factory=list)
    critical_missing_info: list[str] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    voltage_rails: dict[str, float] = Field(default_factory=dict)
    total_estimated_cost: float = 0.0
    status: str = "draft"


class BOMEntry(BaseModel):
    module_id: str
    module_name: str
    part_mpn: Optional[str] = None
    part_id: Optional[str] = None
    quantity: int = 1
    source: str = ""
    unit_price: float = 0.0
    subtotal: float = 0.0
    status: str = "pending"
    notes: str = ""
