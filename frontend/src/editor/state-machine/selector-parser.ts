/**
 * Selector parser — parses @e[...] parameter context for completion.
 */

/** Selector parameter definition with description */
export interface SelectorParamDef {
  name: string
  description: string
  /** Value type hint for completion UI */
  valueType: 'entity' | 'gamemode' | 'string' | 'int' | 'float' | 'compound' | 'boolean' | 'family' | 'permission'
}

/** Known selector parameter definitions for Bedrock Edition */
export const SELECTOR_PARAM_DEFS: SelectorParamDef[] = [
  // --- 实体类型 ---
  { name: 'type', description: '实体类型ID (可用!取反)', valueType: 'entity' },
  // --- 距离 ---
  { name: 'r', description: '最大距离(半径)', valueType: 'float' },
  { name: 'rm', description: '最小距离', valueType: 'float' },
  // --- 位置 ---
  { name: 'x', description: '搜索原点X坐标', valueType: 'float' },
  { name: 'y', description: '搜索原点Y坐标', valueType: 'float' },
  { name: 'z', description: '搜索原点Z坐标', valueType: 'float' },
  // --- 区域体积 ---
  { name: 'dx', description: 'X方向区域范围', valueType: 'float' },
  { name: 'dy', description: 'Y方向区域范围', valueType: 'float' },
  { name: 'dz', description: 'Z方向区域范围', valueType: 'float' },
  // --- 计分板 ---
  { name: 'scores', description: '计分板分数过滤 {目标=值}', valueType: 'compound' },
  // --- 标签与名称 ---
  { name: 'tag', description: '标签过滤 (可重复/取反)', valueType: 'string' },
  { name: 'name', description: '实体名称 (可用!取反)', valueType: 'string' },
  // --- 实体族 ---
  { name: 'family', description: '实体类型族 (可重复/取反)', valueType: 'family' },
  // --- 经验等级 ---
  { name: 'l', description: '最大经验等级', valueType: 'int' },
  { name: 'lm', description: '最小经验等级', valueType: 'int' },
  // --- 游戏模式 ---
  { name: 'm', description: '游戏模式 (可用!取反)', valueType: 'gamemode' },
  // --- 数量限制 ---
  { name: 'c', description: '最大目标数量 (负数=反转排序)', valueType: 'int' },
  // --- 旋转 ---
  { name: 'rx', description: '最大垂直旋转(俯仰角) [-90,90]', valueType: 'float' },
  { name: 'rxm', description: '最小垂直旋转(俯仰角)', valueType: 'float' },
  { name: 'ry', description: '最大水平旋转(偏航角) [-180,180]', valueType: 'float' },
  { name: 'rym', description: '最小水平旋转(偏航角)', valueType: 'float' },
  // --- 物品检测 (基岩版独有) ---
  { name: 'hasitem', description: '物品栏检测 {item=,quantity=,location=,slot=}', valueType: 'compound' },
  // --- 权限检测 (基岩版独有) ---
  { name: 'haspermission', description: '输入权限检测 {权限=enabled/disabled}', valueType: 'permission' },
  // --- 实体属性 (基岩版独有) ---
  { name: 'has_property', description: '实体属性检测 {属性=值}', valueType: 'compound' },
]

/** Flat list of parameter names (for backward compatibility) */
export const SELECTOR_PARAMS = SELECTOR_PARAM_DEFS.map(d => d.name)

/** Quick lookup map: param name → definition */
export const SELECTOR_PARAM_MAP = new Map(SELECTOR_PARAM_DEFS.map(d => [d.name, d]))

export interface SelectorContext {
  /** The parameter name being typed (or just completed) */
  paramName: string | null
  /** Whether we're on the value side of param=value */
  isValue: boolean
  /** The partial text being typed */
  partialInput: string
}

/**
 * Parse a partial selector string like "@e[type=zombie,tag=" or "@e[ty"
 * to determine what's being completed.
 */
export function parseSelectorContext(selector: string): SelectorContext {
  // Find the bracket content
  const bracketIdx = selector.indexOf('[')
  if (bracketIdx === -1) {
    return { paramName: null, isValue: false, partialInput: '' }
  }

  const inside = selector.slice(bracketIdx + 1)
  // Remove trailing ] if present
  const content = inside.endsWith(']') ? inside.slice(0, -1) : inside

  // Split by commas, but respect nested braces/brackets
  // (for scores={...}, hasitem=[{...},{...}], etc.)
  const parts: string[] = []
  let current = ''
  let braceDepth = 0
  let bracketDepth = 0
  for (const ch of content) {
    if (ch === '{') braceDepth++
    else if (ch === '}') braceDepth--
    else if (ch === '[') bracketDepth++
    else if (ch === ']') bracketDepth--
    if (ch === ',' && braceDepth === 0 && bracketDepth === 0) {
      parts.push(current)
      current = ''
    } else {
      current += ch
    }
  }
  parts.push(current)

  // The last part is what the cursor is on
  const lastPart = parts[parts.length - 1]

  if (!lastPart) {
    // After a comma or just opened bracket — expecting param name
    return { paramName: null, isValue: false, partialInput: '' }
  }

  const eqIdx = lastPart.indexOf('=')
  if (eqIdx === -1) {
    // No = sign yet — typing a parameter name
    return { paramName: null, isValue: false, partialInput: lastPart }
  }

  // Has = sign — we know the param name and are typing the value
  const paramName = lastPart.slice(0, eqIdx)
  const valuePart = lastPart.slice(eqIdx + 1)

  return {
    paramName,
    isValue: true,
    partialInput: valuePart,
  }
}
