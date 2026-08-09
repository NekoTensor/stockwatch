/**
 * Store identification.
 *
 * This is *only* about naming the shop the user is standing in. It holds no
 * extraction logic — knowing that a page is Myntra must never be a
 * precondition for reading the product off it. Adding a store here improves
 * the label and the URL heuristics; detection works either way.
 */

import { titleCase } from '../lib/text';

export interface StoreDefinition {
  /** Registry key, also the default adapter id. */
  id: string;
  /** Display name shown in the popup chip. */
  name: string;
  /** Hostname suffixes. "zara.com" also matches "www.zara.com", "m.zara.com". */
  domains: string[];
  /** Brand accent, used for the store chip. */
  accent?: string;
  /** Currency hint, used only when the page itself never states one. */
  currency?: string;
  /** Extra URL shapes that mean "this is a product page" on this store. */
  productUrlPatterns?: RegExp[];
}

export interface StoreIdentity {
  id: string;
  name: string;
  domain: string;
  known: boolean;
  accent?: string;
  currency?: string;
  definition?: StoreDefinition;
}

/**
 * Not every store here has a dedicated adapter, and none needs one: these
 * entries supply the display name, accent and URL heuristics, while detection
 * itself runs through the same generic pipeline for all of them.
 */
export const STORES: StoreDefinition[] = [
  {
    id: 'zara',
    name: 'Zara',
    domains: ['zara.com'],
    accent: '#000000',
    productUrlPatterns: [/-p\d{6,}\.html/i],
  },
  {
    id: 'hm',
    name: 'H&M',
    domains: ['hm.com', 'www2.hm.com'],
    accent: '#e50010',
    productUrlPatterns: [/productpage\.\d+\.html/i],
  },
  {
    id: 'nykaafashion',
    name: 'Nykaa Fashion',
    domains: ['nykaafashion.com'],
    accent: '#e80071',
    currency: 'INR',
    productUrlPatterns: [/\/p\/\d+/i],
  },
  {
    id: 'nykaa',
    name: 'Nykaa',
    domains: ['nykaa.com'],
    accent: '#fc2779',
    currency: 'INR',
    productUrlPatterns: [/\/p\/\d+/i],
  },
  {
    id: 'myntra',
    name: 'Myntra',
    domains: ['myntra.com'],
    accent: '#ff3f6c',
    currency: 'INR',
    productUrlPatterns: [/\/\d+\/buy/i],
  },
  {
    id: 'ajio',
    name: 'AJIO',
    domains: ['ajio.com'],
    accent: '#2f4f8f',
    currency: 'INR',
    productUrlPatterns: [/\/p\/\d+/i],
  },
  {
    id: 'amazon',
    name: 'Amazon',
    domains: [
      'amazon.in',
      'amazon.com',
      'amazon.co.uk',
      'amazon.de',
      'amazon.fr',
      'amazon.it',
      'amazon.es',
      'amazon.ca',
      'amazon.com.au',
      'amazon.co.jp',
      'amazon.ae',
      'amazon.sg',
      'amazon.nl',
      'amazon.se',
      'amazon.pl',
      'amazon.com.br',
      'amazon.com.mx',
    ],
    accent: '#ff9900',
    productUrlPatterns: [/\/(dp|gp\/product)\/[A-Z0-9]{10}/i],
  },
  {
    id: 'flipkart',
    name: 'Flipkart',
    domains: ['flipkart.com'],
    accent: '#2874f0',
    currency: 'INR',
    productUrlPatterns: [/\/p\/itm[a-z0-9]+/i],
  },
  { id: 'nike', name: 'Nike', domains: ['nike.com'], accent: '#111111', productUrlPatterns: [/\/t\//i] },
  {
    id: 'adidas',
    name: 'Adidas',
    domains: ['adidas.com', 'adidas.co.in', 'adidas.co.uk', 'adidas.de', 'adidas.ae'],
    accent: '#000000',
    productUrlPatterns: [/\/[A-Z0-9]{6}\.html/i],
  },
  {
    id: 'uniqlo',
    name: 'Uniqlo',
    domains: ['uniqlo.com'],
    accent: '#ff0000',
    productUrlPatterns: [/\/products\/E\d+/i],
  },
  { id: 'asos', name: 'ASOS', domains: ['asos.com'], accent: '#2d2d2d', productUrlPatterns: [/\/prd\/\d+/i] },
  {
    id: 'decathlon',
    name: 'Decathlon',
    domains: ['decathlon.in', 'decathlon.com', 'decathlon.co.uk', 'decathlon.fr'],
    accent: '#0082c3',
    productUrlPatterns: [/\/p\/[a-z0-9-]+\/_\//i],
  },
  {
    id: 'sephora',
    name: 'Sephora',
    domains: ['sephora.com', 'sephora.co.uk', 'sephora.fr', 'sephora.in'],
    accent: '#000000',
    productUrlPatterns: [/\/product\//i],
  },
  { id: 'meesho', name: 'Meesho', domains: ['meesho.com'], accent: '#570d5f', currency: 'INR' },
  { id: 'tatacliq', name: 'Tata CLiQ', domains: ['tatacliq.com'], accent: '#c11c4d', currency: 'INR' },
  { id: 'westside', name: 'Westside', domains: ['westside.com'], accent: '#000000', currency: 'INR' },
  {
    id: 'marksandspencer',
    name: 'Marks & Spencer',
    domains: ['marksandspencer.com', 'marksandspencer.in'],
    accent: '#00543c',
  },
  { id: 'shoppersstop', name: 'Shoppers Stop', domains: ['shoppersstop.com'], accent: '#c8102e', currency: 'INR' },
  { id: 'bewakoof', name: 'Bewakoof', domains: ['bewakoof.com'], accent: '#fdd835', currency: 'INR' },
  { id: 'snitch', name: 'Snitch', domains: ['snitch.com', 'snitch.co.in'], accent: '#111111', currency: 'INR' },
  { id: 'levis', name: "Levi's", domains: ['levi.in', 'levi.com', 'levis.in'], accent: '#c41230' },
  { id: 'puma', name: 'Puma', domains: ['puma.com'], accent: '#111111' },
  { id: 'zalando', name: 'Zalando', domains: ['zalando.com', 'zalando.co.uk', 'zalando.de'], accent: '#ff6900' },
  { id: 'shein', name: 'SHEIN', domains: ['shein.com', 'shein.in'], accent: '#000000' },
  { id: 'lifestylestores', name: 'Lifestyle', domains: ['lifestylestores.com'], accent: '#e4002b', currency: 'INR' },
  { id: 'pantaloons', name: 'Pantaloons', domains: ['pantaloons.com'], accent: '#f6a600', currency: 'INR' },
  { id: 'mango', name: 'Mango', domains: ['mango.com', 'shop.mango.com'], accent: '#000000' },
  { id: 'ikea', name: 'IKEA', domains: ['ikea.com'], accent: '#0058a3' },
  { id: 'croma', name: 'Croma', domains: ['croma.com'], accent: '#12968a', currency: 'INR' },
  { id: 'reliancedigital', name: 'Reliance Digital', domains: ['reliancedigital.in'], accent: '#00539f', currency: 'INR' },
];

/** Amazon runs one storefront per country; the TLD is the region. */
const AMAZON_REGIONS: Record<string, string> = {
  'amazon.in': 'Amazon India',
  'amazon.com': 'Amazon',
  'amazon.co.uk': 'Amazon UK',
  'amazon.de': 'Amazon Germany',
  'amazon.fr': 'Amazon France',
  'amazon.it': 'Amazon Italy',
  'amazon.es': 'Amazon Spain',
  'amazon.ca': 'Amazon Canada',
  'amazon.com.au': 'Amazon Australia',
  'amazon.co.jp': 'Amazon Japan',
  'amazon.ae': 'Amazon UAE',
  'amazon.sg': 'Amazon Singapore',
  'amazon.com.br': 'Amazon Brazil',
  'amazon.com.mx': 'Amazon Mexico',
};

function matchesDomain(hostname: string, domain: string): boolean {
  return hostname === domain || hostname.endsWith(`.${domain}`);
}

/** Longest matching domain wins, so "shop.mango.com" beats "mango.com". */
export function findStoreDefinition(hostname: string): { def: StoreDefinition; domain: string } | undefined {
  let best: { def: StoreDefinition; domain: string } | undefined;
  for (const def of STORES) {
    for (const domain of def.domains) {
      if (!matchesDomain(hostname, domain)) continue;
      if (!best || domain.length > best.domain.length) best = { def, domain };
    }
  }
  return best;
}

/**
 * Turn an unrecognised hostname into something presentable.
 * "shop.some-boutique.co.uk" -> "Some Boutique"
 */
export function prettifyHostname(hostname: string): string {
  const parts = hostname.split('.').filter(Boolean);
  if (!parts.length) return 'Unknown Store';

  // "co" in "co.uk" / "com" in "com.au" is part of the TLD, not the brand.
  const tldFragments = new Set(['co', 'com', 'net', 'org', 'gov', 'ac', 'edu']);
  let index = Math.max(parts.length - 2, 0);
  if (index >= 1 && tldFragments.has(parts[index])) index -= 1;

  let core = parts[index];
  const generic = new Set(['shop', 'store', 'www', 'm', 'mobile']);
  if (generic.has(core)) {
    core = parts.find((part) => !generic.has(part) && !tldFragments.has(part)) ?? core;
  }

  return titleCase(core.replace(/-/g, ' ')) || 'Unknown Store';
}

/** Name the shop. Always succeeds — unknown stores get a derived label. */
export function identifyStore(hostname: string): StoreIdentity {
  const host = hostname.toLowerCase().replace(/^www\d*\./, '');
  const match = findStoreDefinition(host);

  if (!match) {
    return {
      id: 'generic',
      name: prettifyHostname(host) || 'Unknown Store',
      domain: host,
      known: false,
    };
  }

  const { def, domain } = match;
  const name = def.id === 'amazon' ? (AMAZON_REGIONS[domain] ?? def.name) : def.name;

  return {
    id: def.id,
    name,
    domain: host,
    known: true,
    accent: def.accent,
    currency: def.currency,
    definition: def,
  };
}
