/**
 * The vocabulary the whole extension speaks.
 *
 * Everything that comes off a page — no matter which store, which extraction
 * layer, or which adapter produced it — is normalised into `ProductData`
 * before it reaches the UI. The UI never knows what a "Myntra pdpData" or an
 * "Amazon twister" is; it only knows about products and variants.
 */

/** Where a piece of information came from. Ordered by trustworthiness. */
export type SourceLayer =
  | 'jsonld' // schema.org Product in <script type="application/ld+json">
  | 'microdata' // schema.org via itemprop/itemtype attributes
  | 'embedded' // __NEXT_DATA__, dataLayer, __PRELOADED_STATE__, …
  | 'opengraph' // og:* / product:* meta tags
  | 'meta' // twitter:*, itemprop meta, <title>, canonical
  | 'adapter' // a store-specific adapter claimed this field
  | 'dom' // visual/structural heuristics over the rendered page
  | 'url'; // parsed out of the address itself

/**
 * Stock is deliberately three-valued. A request that failed, a page that
 * hasn't hydrated, or a size widget we didn't recognise must never be
 * reported as "out of stock" — that is how trackers cry wolf.
 */
export type StockStatus = 'in_stock' | 'out_of_stock' | 'unknown';

/**
 * Products are not just clothes. A "variant" is any user-selectable option
 * that can independently sell out: a size, a shade, a storage tier, a length.
 */
export type VariantType =
  | 'size'
  | 'color'
  | 'shade'
  | 'capacity'
  | 'length'
  | 'flavor'
  | 'style'
  | 'generic';

export interface Variant {
  /** Stable-ish identifier: the store's own id when we can find one. */
  id: string;
  /** What the shopper sees on the button: "M", "UK 8", "256GB", "Shade 01". */
  name: string;
  type: VariantType;
  availability: StockStatus;
  sku?: string;
  /** Some stores price per variant (e.g. storage tiers). */
  price?: number;
  /** Human label for the group this variant belongs to ("Size", "Colour"). */
  group?: string;
  source: SourceLayer;
}

export interface PriceData {
  currency?: string;
  currentPrice?: number;
  originalPrice?: number;
  discountPercentage?: number;
}

export interface ProductData {
  /** Display name of the shop: "Zara", "Myntra", "Unknown Store". */
  store: string;
  /** Registry key: "zara", "myntra", "generic". */
  storeId: string;
  storeDomain: string;

  productName?: string;
  brand?: string;

  /** The tab's URL, cleaned of tracking parameters. */
  productUrl: string;
  /** rel=canonical / og:url when the page offers one. */
  canonicalUrl?: string;

  productId?: string;
  sku?: string;

  imageUrl?: string;
  images: string[];

  category?: string;
  description?: string;

  currency?: string;
  currentPrice?: number;
  originalPrice?: number;
  discountPercentage?: number;

  availability: StockStatus;
  variants: Variant[];

  /** ISO timestamp of when the snapshot was taken. */
  detectedAt: string;
}

/**
 * Outcome of a detection run.
 *
 * `partial` is a first-class result, not a failure: a page where we found the
 * product and its price but couldn't read the size widget is still worth
 * tracking for price alone, and the UI says so explicitly.
 */
export type DetectionStatus =
  | 'detected'
  | 'partial'
  | 'not_a_product'
  | 'unsupported_page'
  | 'error';

export interface DetectionResult {
  status: DetectionStatus;
  product?: ProductData;
  /** 0–100. How sure we are that this page is a product page. */
  confidence: number;
  /** Fields the UI should tell the user we could not read. */
  missing: string[];
  warnings: string[];
  /** field name → the layer that won it. Powers the "Detection details" panel. */
  provenance: Partial<Record<keyof ProductData, SourceLayer>>;
  layersUsed: SourceLayer[];
  adapterId: string;
  durationMs: number;
  /** Present when status === 'error'. */
  error?: string;
}

/**
 * What an extraction layer hands back before merging. Every layer returns the
 * same shape, which is what lets us add layers without touching the merger.
 */
export interface Candidate {
  source: SourceLayer;
  data: Partial<Omit<ProductData, 'variants' | 'images'>> & {
    variants?: Variant[];
    images?: string[];
  };
  /** Layer-local confidence 0–1, used to break ties between equal priorities. */
  confidence?: number;
}

/** Everything a layer or adapter is allowed to look at. */
export interface DetectionContext {
  doc: Document;
  url: string;
  hostname: string;
  /**
   * Page globals harvested from the MAIN world (`window.__NEXT_DATA__`,
   * `dataLayer`, …). Serialised to plain JSON before it crosses the world
   * boundary, so it is always structured-clone safe.
   */
  pageGlobals: Record<string, unknown>;
}

/** A tracking draft the popup stores locally until the backend exists. */
export interface TrackingDraft {
  id: string;
  product: ProductData;
  variantIds: string[];
  trackStock: boolean;
  trackPrice: boolean;
  targetPrice?: number;
  createdAt: string;
}
