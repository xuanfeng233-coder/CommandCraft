/**
 * Shared tooltip DOM building utilities.
 * Used by mc-hover.ts (hover tooltips) and mc-completion.ts (completion info panels).
 */
import type { CommandSyntaxDef } from '../state-machine/types'

export function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export function createTooltipDOM(sections: Array<{ cls: string; html: string }>): HTMLElement {
  const container = document.createElement('div')
  container.className = 'mc-hover-tooltip'
  for (const sec of sections) {
    const el = document.createElement('div')
    el.className = sec.cls
    el.innerHTML = sec.html
    container.appendChild(el)
  }
  return container
}

/** Build info DOM for a command definition (completion info + hover) */
export function createCommandInfoDOM(cmd: CommandSyntaxDef): HTMLElement {
  const sections: Array<{ cls: string; html: string }> = []

  sections.push({
    cls: 'mc-hover-title',
    html: `<span class="mc-hover-cmd">/${escapeHtml(cmd.name)}</span>` +
      `<span class="mc-hover-badge">${escapeHtml(cmd.category)}</span>`,
  })

  sections.push({
    cls: 'mc-hover-syntax',
    html: escapeHtml(cmd.syntax),
  })

  sections.push({
    cls: 'mc-hover-desc',
    html: escapeHtml(cmd.description),
  })

  if (cmd.parameters.length > 0) {
    const paramLines = cmd.parameters.map(p => {
      const req = p.required
        ? '<span class="mc-hover-req">必填</span>'
        : '<span class="mc-hover-opt">可选</span>'
      return `<div class="mc-hover-param-item">${req} <code>${escapeHtml(p.name)}</code>: ${escapeHtml(p.type)}${p.description ? ' — ' + escapeHtml(p.description) : ''}</div>`
    })
    sections.push({
      cls: 'mc-hover-params',
      html: paramLines.join(''),
    })
  }

  return createTooltipDOM(sections)
}

/** Build info DOM for an ID entry (items, blocks, entities, etc.) */
export function createIdInfoDOM(
  entry: { id: string; name?: string; description?: string; category?: string },
  categoryLabel: string,
): HTMLElement {
  const sections: Array<{ cls: string; html: string }> = []

  sections.push({
    cls: 'mc-hover-title',
    html: `<code>${escapeHtml(entry.id)}</code>` +
      (entry.name ? ` <span class="mc-hover-name">${escapeHtml(entry.name)}</span>` : '') +
      ` <span class="mc-hover-badge">${escapeHtml(categoryLabel)}</span>`,
  })

  if (entry.description) {
    sections.push({ cls: 'mc-hover-desc', html: escapeHtml(entry.description) })
  }
  if (entry.category) {
    sections.push({ cls: 'mc-hover-meta', html: `分类: ${escapeHtml(entry.category)}` })
  }

  return createTooltipDOM(sections)
}

/** Build info DOM for a fixed option value */
export function createFixedOptionInfoDOM(
  value: string,
  description: string,
  typeName: string,
): HTMLElement {
  return createTooltipDOM([
    {
      cls: 'mc-hover-title',
      html: `<code>${escapeHtml(value)}</code> <span class="mc-hover-badge">${escapeHtml(typeName)}</span>`,
    },
    { cls: 'mc-hover-desc', html: escapeHtml(description) },
  ])
}

/** Build info DOM for a selector parameter */
export function createSelectorParamInfoDOM(
  name: string,
  valueType: string,
  description: string,
): HTMLElement {
  return createTooltipDOM([
    {
      cls: 'mc-hover-title',
      html: `<code>${escapeHtml(name)}</code> <span class="mc-hover-badge">${escapeHtml(valueType)}</span>`,
    },
    { cls: 'mc-hover-desc', html: escapeHtml(description) },
  ])
}
