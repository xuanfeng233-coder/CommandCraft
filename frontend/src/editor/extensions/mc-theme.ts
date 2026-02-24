/**
 * CodeMirror 6 theme + highlight style matching the MC pixel theme.
 * Uses CSS custom properties from variables.css.
 *
 * Includes styles for:
 * - Base editor theme
 * - Syntax highlighting (StreamLanguage)
 * - Hover tooltips
 * - Semantic highlighting (ID categories)
 * - Inline decorations (color codes, brackets, coord labels)
 */
import { EditorView } from '@codemirror/view'
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

/** Base editor theme — dark MC pixel style */
export const mcEditorTheme = EditorView.theme(
  {
    '&': {
      backgroundColor: 'var(--mc-bg-deep)',
      color: 'var(--mc-text-primary)',
      fontFamily: "'GNU Unifont', var(--mc-font-mono)",
      fontSize: '14px',
      lineHeight: '1.6',
    },
    '.cm-content': {
      caretColor: 'var(--mc-gold)',
      padding: '8px 0',
    },
    '.cm-cursor, .cm-dropCursor': {
      borderLeftColor: 'var(--mc-gold)',
      borderLeftWidth: '2px',
    },
    '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
      backgroundColor: 'rgba(221, 165, 32, 0.25)',
    },
    '.cm-activeLine': {
      backgroundColor: 'rgba(255, 255, 255, 0.04)',
    },
    '.cm-gutters': {
      backgroundColor: 'var(--mc-bg-main)',
      color: 'var(--mc-text-dim)',
      border: 'none',
      borderRight: '2px solid var(--mc-border)',
    },
    '.cm-activeLineGutter': {
      backgroundColor: 'rgba(255, 255, 255, 0.06)',
      color: 'var(--mc-text-secondary)',
    },
    '.cm-lineNumbers .cm-gutterElement': {
      padding: '0 8px 0 4px',
      minWidth: '32px',
    },
    // Autocomplete dropdown
    '.cm-tooltip': {
      backgroundColor: 'var(--mc-bg-card)',
      border: '2px solid var(--mc-border)',
      boxShadow: '4px 4px 0 rgba(0,0,0,0.5)',
      color: 'var(--mc-text-primary)',
      fontFamily: "'GNU Unifont', var(--mc-font-mono)",
      fontSize: '13px',
    },
    '.cm-tooltip-autocomplete': {
      '& > ul': {
        fontFamily: "'GNU Unifont', var(--mc-font-mono)",
        maxHeight: '200px',
      },
      '& > ul > li': {
        padding: '4px 8px',
        lineHeight: '1.4',
      },
      '& > ul > li[aria-selected]': {
        backgroundColor: 'var(--mc-bg-hover)',
        color: 'var(--mc-gold)',
      },
    },
    // Lint diagnostics
    '.cm-diagnostic-error': {
      borderLeft: '3px solid var(--mc-red)',
      backgroundColor: 'rgba(176, 46, 38, 0.15)',
      color: 'var(--mc-text-primary)',
      padding: '4px 8px',
    },
    '.cm-diagnostic-warning': {
      borderLeft: '3px solid var(--mc-gold)',
      backgroundColor: 'rgba(221, 165, 32, 0.1)',
      color: 'var(--mc-text-primary)',
      padding: '4px 8px',
    },
    '.cm-lintRange-error': {
      backgroundImage: 'none',
      textDecoration: 'wavy underline var(--mc-red)',
      textUnderlineOffset: '3px',
    },
    '.cm-lintRange-warning': {
      backgroundImage: 'none',
      textDecoration: 'wavy underline var(--mc-gold)',
      textUnderlineOffset: '3px',
    },
    // Scrollbar
    '.cm-scroller': {
      overflow: 'auto',
      scrollbarWidth: 'thin',
      scrollbarColor: 'var(--mc-border) transparent',
    },

    // ─── Hover Tooltip ──────────────────────────────────────

    '.mc-hover-tooltip': {
      padding: '8px 12px',
      maxWidth: '400px',
      lineHeight: '1.5',
    },
    '.mc-hover-title': {
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      fontSize: '14px',
      fontWeight: 'bold',
      marginBottom: '4px',
    },
    '.mc-hover-cmd': {
      color: 'var(--mc-syn-command)',
    },
    '.mc-hover-name': {
      color: 'var(--mc-text-secondary)',
      fontWeight: 'normal',
    },
    '.mc-hover-badge': {
      display: 'inline-block',
      padding: '1px 6px',
      fontSize: '10px',
      borderRadius: '2px',
      backgroundColor: 'rgba(255,255,255,0.1)',
      color: 'var(--mc-text-dim)',
      fontWeight: 'normal',
    },
    '.mc-hover-syntax': {
      fontFamily: 'var(--mc-font-mono)',
      fontSize: '12px',
      color: 'var(--mc-text-secondary)',
      padding: '4px 6px',
      backgroundColor: 'rgba(0,0,0,0.2)',
      borderRadius: '2px',
      marginBottom: '4px',
      overflowX: 'auto',
      whiteSpace: 'pre-wrap',
    },
    '.mc-hover-desc': {
      color: 'var(--mc-text-primary)',
      fontSize: '12px',
    },
    '.mc-hover-params': {
      marginTop: '6px',
      fontSize: '11px',
    },
    '.mc-hover-param-item': {
      padding: '1px 0',
      color: 'var(--mc-text-secondary)',
    },
    '.mc-hover-param-item code': {
      color: 'var(--mc-syn-optional)',
    },
    '.mc-hover-req': {
      color: 'var(--mc-syn-number)',
      fontSize: '10px',
    },
    '.mc-hover-opt': {
      color: 'var(--mc-text-dim)',
      fontSize: '10px',
    },
    '.mc-hover-meta': {
      color: 'var(--mc-text-dim)',
      fontSize: '11px',
      marginTop: '4px',
    },
    '.mc-hover-error': {
      color: 'var(--mc-syn-number)',
      fontSize: '12px',
    },
    '.mc-hover-invalid': {
      fontWeight: 'bold',
    },

    // ─── Semantic Highlighting ──────────────────────────────

    '.mc-sem-item': {
      color: 'var(--mc-sem-item) !important',
    },
    '.mc-sem-block': {
      color: 'var(--mc-sem-block) !important',
    },
    '.mc-sem-entity': {
      color: 'var(--mc-sem-entity) !important',
    },
    '.mc-sem-effect': {
      color: 'var(--mc-sem-effect) !important',
    },
    '.mc-sem-enchant': {
      color: 'var(--mc-sem-enchant) !important',
    },
    '.mc-sem-particle': {
      color: 'var(--mc-sem-particle) !important',
    },
    '.mc-sem-sound': {
      color: 'var(--mc-sem-sound) !important',
    },
    '.mc-sem-biome': {
      color: 'var(--mc-sem-particle) !important',
    },
    '.mc-sem-enum': {
      color: 'var(--mc-sem-enum) !important',
    },
    '.mc-sem-invalid': {
      textDecoration: 'wavy underline var(--mc-red) !important',
      textUnderlineOffset: '3px',
    },

    // ─── Inline Decorations ─────────────────────────────────

    '.mc-deco-color-swatch': {
      display: 'inline-block',
      width: '10px',
      height: '10px',
      marginLeft: '2px',
      marginRight: '1px',
      verticalAlign: 'middle',
      borderRadius: '1px',
      border: '1px solid rgba(255,255,255,0.2)',
    },
    '.mc-deco-coord-axis': {
      display: 'inline-block',
      fontSize: '9px',
      fontWeight: 'bold',
      color: 'var(--mc-text-dim)',
      marginRight: '1px',
      verticalAlign: 'super',
      lineHeight: '1',
    },
    '.mc-deco-bracket-match': {
      backgroundColor: 'rgba(221, 165, 32, 0.3)',
      borderRadius: '1px',
      outline: '1px solid rgba(221, 165, 32, 0.5)',
    },
    '.mc-deco-separator': {
      borderBottom: '1px solid rgba(255,255,255,0.06)',
    },

    // ─── Inlay Hints ──────────────────────────────────────────

    '.mc-inlay-hint': {
      display: 'inline-block',
      color: 'var(--mc-text-dim)',
      fontSize: '11px',
      fontStyle: 'italic',
      opacity: '0.7',
      padding: '0 2px',
      verticalAlign: 'baseline',
    },

    // ─── Signature Help Tooltip ───────────────────────────────

    '.mc-sig-tooltip': {
      padding: '6px 10px',
      maxWidth: '450px',
      lineHeight: '1.5',
    },
    '.mc-sig-syntax': {
      fontFamily: "'GNU Unifont', var(--mc-font-mono)",
      fontSize: '12px',
      whiteSpace: 'pre-wrap',
    },
    '.mc-sig-cmd': {
      color: 'var(--mc-syn-command)',
      fontWeight: 'bold',
    },
    '.mc-sig-param': {
      color: 'var(--mc-text-dim)',
    },
    '.mc-sig-param-active': {
      color: 'var(--mc-gold)',
      fontWeight: 'bold',
      textDecoration: 'underline',
      textUnderlineOffset: '2px',
    },
    '.mc-sig-desc': {
      color: 'var(--mc-text-secondary)',
      fontSize: '11px',
      marginTop: '4px',
      borderTop: '1px solid rgba(255,255,255,0.08)',
      paddingTop: '4px',
    },

    // ─── Quick Fix Gutter ─────────────────────────────────────

    '.mc-quick-fix-gutter': {
      width: '16px',
    },
    '.mc-quick-fix-bulb': {
      cursor: 'pointer',
      fontSize: '12px',
      lineHeight: '1',
      display: 'inline-block',
      userSelect: 'none',
    },
    '.mc-quick-fix-menu': {
      backgroundColor: 'var(--mc-bg-card)',
      border: '2px solid var(--mc-border)',
      boxShadow: '4px 4px 0 rgba(0,0,0,0.5)',
      fontFamily: "'GNU Unifont', var(--mc-font-mono)",
      fontSize: '12px',
      minWidth: '180px',
      maxWidth: '320px',
      padding: '4px 0',
    },
    '.mc-quick-fix-header': {
      padding: '4px 10px',
      color: 'var(--mc-text-dim)',
      fontSize: '11px',
      borderBottom: '1px solid rgba(255,255,255,0.06)',
    },
    '.mc-quick-fix-item': {
      padding: '4px 10px',
      cursor: 'pointer',
      color: 'var(--mc-text-primary)',
    },
    '.mc-quick-fix-item:hover': {
      backgroundColor: 'var(--mc-bg-hover)',
      color: 'var(--mc-gold)',
    },

    // ─── Completion Info Panel ─────────────────────────────────

    '.cm-completionInfo': {
      padding: '0',
      border: 'none',
      backgroundColor: 'var(--mc-bg-card)',
      maxWidth: '350px',
      maxHeight: '250px',
      overflowY: 'auto',
      scrollbarWidth: 'thin',
      scrollbarColor: 'var(--mc-border) transparent',
    },
    '.cm-completionInfo .mc-hover-tooltip': {
      padding: '8px 10px',
      maxWidth: 'none',
    },
  },
  { dark: true }
)

/** Syntax highlight style mapping StreamLanguage tokens to MC colors */
const mcHighlight = HighlightStyle.define([
  // /command and command name → green
  { tag: t.keyword, color: 'var(--mc-syn-command)', fontWeight: 'bold' },
  // @selector → magenta
  { tag: t.className, color: 'var(--mc-syn-selector)' },
  // "string" → orange
  { tag: t.string, color: 'var(--mc-syn-string)' },
  // 123 → red
  { tag: t.number, color: 'var(--mc-syn-number)' },
  // ~5 ^-3 relative coords → cyan
  { tag: t.atom, color: 'var(--mc-syn-optional)' },
  // as, at, if, run, true, false → yellow
  { tag: t.operator, color: 'var(--mc-syn-required)' },
  // Generic identifiers (param values) → light text
  { tag: t.variableName, color: 'var(--mc-text-primary)' },
  // # comments → dim
  { tag: t.lineComment, color: 'var(--mc-text-dim)', fontStyle: 'italic' },
  // JSON braces
  { tag: t.brace, color: 'var(--mc-text-secondary)' },
  // Punctuation
  { tag: t.punctuation, color: 'var(--mc-text-dim)' },
])

/** Combined theme + highlighting extension */
export const mcTheme = [mcEditorTheme, syntaxHighlighting(mcHighlight)]
