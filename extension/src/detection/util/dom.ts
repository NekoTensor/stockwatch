/**
 * DOM helpers for the heuristic layer.
 *
 * These are written to behave sensibly under jsdom as well as in a real
 * browser: jsdom reports every element as zero-sized, so nothing here treats
 * "has no box" as "is hidden". Only explicit hiding counts.
 */

const HIDDEN_DISPLAY = /^(none)$/i;

export function queryAll(root: ParentNode, selector: string): Element[] {
  try {
    return Array.from(root.querySelectorAll(selector));
  } catch {
    return []; // A selector the engine rejects should never abort detection.
  }
}

function styleOf(el: Element): CSSStyleDeclaration | undefined {
  const view = el.ownerDocument?.defaultView;
  if (!view?.getComputedStyle) return undefined;
  try {
    return view.getComputedStyle(el);
  } catch {
    return undefined;
  }
}

/** Explicitly hidden: display:none, visibility:hidden, [hidden], aria-hidden. */
export function isHidden(el: Element): boolean {
  if (el.hasAttribute('hidden')) return true;
  if (el.getAttribute('aria-hidden') === 'true') return true;

  const style = styleOf(el);
  if (style) {
    if (HIDDEN_DISPLAY.test(style.display)) return true;
    if (style.visibility === 'hidden' || style.visibility === 'collapse') return true;
    const opacity = Number.parseFloat(style.opacity);
    if (Number.isFinite(opacity) && opacity === 0) return true;
  }

  return false;
}

/** True when the element or any ancestor is explicitly hidden. */
export function isHiddenDeep(el: Element): boolean {
  let node: Element | null = el;
  let hops = 0;
  while (node && hops < 12) {
    if (isHidden(node)) return true;
    node = node.parentElement;
    hops += 1;
  }
  return false;
}

export function textOf(el: Element | null | undefined): string {
  if (!el) return '';
  return (el.textContent ?? '').replace(/\s+/g, ' ').trim();
}

/**
 * What a shopper would call this control. Size buttons are frequently an empty
 * `<button>` wrapping an `<input>`, so fall back through the a11y attributes.
 */
export function accessibleLabel(el: Element): string {
  const direct = textOf(el);
  if (direct) return direct;

  for (const attr of ['aria-label', 'title', 'data-value', 'data-size', 'value', 'alt']) {
    const value = el.getAttribute(attr);
    if (value?.trim()) return value.trim();
  }

  const input = el.querySelector('input');
  const inputValue = input?.getAttribute('value');
  return inputValue?.trim() ?? '';
}

const DISABLED_CLASS =
  /(^|[\s_-])(disabled|is-disabled|unavailable|is-unavailable|out-of-stock|outofstock|sold-?out|soldout|crossed|strike|not-available|inactive|greyed|grayed)([\s_-]|$)/i;

/**
 * Class names come in kebab-case, snake_case *and* camelCase
 * (`swatchUnavailable`). Inserting a separator at each camel boundary lets one
 * kebab-oriented pattern match all three conventions.
 */
function separateCamelCase(value: string): string {
  return value.replace(/([a-z0-9])([A-Z])/g, '$1-$2');
}

function classNameOf(el: Element): string {
  const raw = typeof el.className === 'string' ? el.className : (el.getAttribute('class') ?? '');
  return separateCamelCase(raw);
}

/**
 * Is this variant control switched off? Stores signal it half a dozen ways and
 * almost never the same way twice, so check all of them.
 */
export function isDisabledLike(el: Element): boolean {
  if (el.hasAttribute('disabled')) return true;
  if (el.getAttribute('aria-disabled') === 'true') return true;

  const dataAvailable = el.getAttribute('data-available') ?? el.getAttribute('data-in-stock');
  if (dataAvailable !== null && /^(false|0|no)$/i.test(dataAvailable)) return true;

  const dataOut = el.getAttribute('data-out-of-stock') ?? el.getAttribute('data-sold-out');
  if (dataOut !== null && /^(true|1|yes)$/i.test(dataOut)) return true;

  if (DISABLED_CLASS.test(classNameOf(el))) return true;

  const input = el.querySelector('input');
  if (input?.hasAttribute('disabled')) return true;

  const style = styleOf(el);
  if (style) {
    if (style.textDecorationLine?.includes('line-through')) return true;
    if (style.pointerEvents === 'none') return true;
    const opacity = Number.parseFloat(style.opacity);
    if (Number.isFinite(opacity) && opacity > 0 && opacity < 0.55) return true;
  }

  return false;
}

/** Struck-through text is how every store on earth renders the old price. */
export function isStruckThrough(el: Element): boolean {
  if (['S', 'DEL', 'STRIKE'].includes(el.tagName)) return true;

  if (
    /(strike|struck|line-?through|mrp|was-?price|old-?price|list-?price|original|compare|regular|slashed|basis-?price)/i.test(
      classNameOf(el),
    )
  ) {
    return true;
  }

  const style = styleOf(el);
  return Boolean(style?.textDecorationLine?.includes('line-through'));
}

/**
 * Clothing sizes, shoe sizes, storage tiers, volumes — the tokens that mark a
 * button as a variant selector rather than ordinary navigation.
 */
export const VARIANT_TOKEN = new RegExp(
  [
    '^(XXS|XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL|5XL)$', // apparel
    '^(UK|US|EU|IND?)\\s?\\d{1,2}(\\.5)?$', // shoes
    '^\\d{1,2}(\\.5)?$', // bare shoe/waist size
    '^\\d{2,3}\\s?(CM|MM|IN|INCH|INCHES)$', // dimensions
    '^\\d{1,4}\\s?(GB|TB|MB)$', // storage
    '^\\d{1,4}\\s?(ML|L|G|KG|OZ)$', // volume / weight
    '^(SHADE|COLOU?R|TONE)\\s?\\d+$', // cosmetics
    '^\\d{2}\\s?/\\s?\\d{2}$', // waist/length e.g. 32/34
    '^(ONE ?SIZE|FREE ?SIZE|OS|STANDARD|REGULAR)$',
  ].join('|'),
  'i',
);

/** Container hints that say "the buttons inside me choose a variant". */
export const VARIANT_CONTAINER_HINT =
  /(size|sizes|variant|variation|swatch|shade|colou?r|option|selector|picker|dimension|capacity|storage|fit|length)/i;

/**
 * Best-effort label for the group a control belongs to ("Select size",
 * "Colour", "Storage"). Used to type the variants we find.
 */
export function groupLabelFor(el: Element, maxHops = 4): string {
  let node: Element | null = el.parentElement;
  let hops = 0;

  while (node && hops < maxHops) {
    const heading = node.querySelector('label, legend, h2, h3, h4, [class*="label" i], [class*="title" i]');
    const text = textOf(heading);
    if (text && text.length < 60) return text;

    const attrs = [
      node.getAttribute('aria-label'),
      node.getAttribute('data-testid'),
      node.getAttribute('id'),
      typeof node.className === 'string' ? node.className : null,
    ]
      .filter(Boolean)
      .join(' ');
    if (VARIANT_CONTAINER_HINT.test(attrs)) return attrs;

    node = node.parentElement;
    hops += 1;
  }

  return '';
}

/** How many edges apart two nodes are — a cheap proxy for "visually near". */
export function domDistance(a: Element, b: Element, cap = 25): number {
  const ancestors = new Map<Element, number>();
  let node: Element | null = a;
  let depth = 0;
  while (node && depth <= cap) {
    ancestors.set(node, depth);
    node = node.parentElement;
    depth += 1;
  }

  node = b;
  depth = 0;
  while (node && depth <= cap) {
    const up = ancestors.get(node);
    if (up !== undefined) return up + depth;
    node = node.parentElement;
    depth += 1;
  }

  return cap * 2;
}

export function metaContent(doc: Document, selectors: string[]): string | undefined {
  for (const selector of selectors) {
    for (const el of queryAll(doc, selector)) {
      const value = el.getAttribute('content') ?? el.getAttribute('value') ?? el.getAttribute('href');
      if (value?.trim()) return value.trim();
    }
  }
  return undefined;
}
