PART_SCHEMAS = {
    "ldo": {
        "label": "LDO 稳压器",
        "required": ["vin", "vout", "current"],
        "parameters": ["vin_min", "vin_max", "vout", "iout_max", "dropout_mv", "noise_uvrms", "iq_ua", "package"],
        "guidance": "说明输入电压、输出电压、最大负载电流、噪声和封装偏好。",
    },
    "buck": {
        "label": "Buck DC-DC",
        "required": ["vin", "vout", "current"],
        "parameters": ["vin_min", "vin_max", "vout_min", "vout_max", "iout_max", "switching_frequency_khz", "efficiency_pct", "package"],
        "guidance": "说明输入电压范围、输出电压、负载电流、效率、纹波和电感尺寸限制。",
    },
    "adc": {
        "label": "ADC 模数转换器",
        "required": ["resolution_bits", "channels", "interface"],
        "parameters": ["resolution_bits", "sample_rate_ksps", "channels", "interface", "vin_min", "vin_max", "input_type", "reference"],
        "guidance": "说明分辨率、采样率、通道数、接口、输入范围和是否差分输入。",
    },
    "dac": {
        "label": "DAC 数模转换器",
        "required": ["resolution_bits", "channels", "interface"],
        "parameters": ["resolution_bits", "update_rate_ksps", "channels", "interface", "vin_min", "vin_max", "output_type", "reference"],
        "guidance": "说明分辨率、更新率、通道数、接口、输出范围/类型和参考源。",
    },
    "mcu": {
        "label": "MCU 微控制器",
        "required": ["interface"],
        "parameters": ["core", "flash_kb", "ram_kb", "gpio", "interfaces", "vin_min", "vin_max", "package"],
        "guidance": "说明内核性能、Flash/RAM、GPIO、外设接口、供电电压和封装。",
    },
}


def missing_fields(requirement: dict) -> list[str]:
    category = requirement.get("category")
    if category not in PART_SCHEMAS:
        return ["category"]
    return [field for field in PART_SCHEMAS[category]["required"] if requirement.get(field) in (None, "", [])]


def schema_guidance(category: str | None) -> str:
    if category in PART_SCHEMAS:
        return PART_SCHEMAS[category]["guidance"]
    return "先明确器件类型，例如 LDO、Buck、ADC、DAC、MCU，再补充关键电压、电流、接口或精度指标。"
