/**
 * The adapter registry.
 *
 * Adding a store is a new file and one `register()` call. Nothing in the
 * detection pipeline changes, which is the whole point of the design.
 */

import type { DetectionContext } from '../lib/types';
import { AdidasAdapter } from './adidas';
import { AjioAdapter } from './ajio';
import { AmazonAdapter } from './amazon';
import { GenericAdapter } from './generic';
import { HmAdapter } from './hm';
import { MyntraAdapter } from './myntra';
import { NikeAdapter } from './nike';
import { NykaaAdapter } from './nykaa';
import { UniqloAdapter } from './uniqlo';
import { ZaraAdapter } from './zara';
import type { StoreAdapter } from './types';

export class StoreRegistry {
  private readonly adapters: StoreAdapter[] = [];

  constructor(private readonly fallback: StoreAdapter = GenericAdapter) {}

  register(adapter: StoreAdapter): this {
    if (this.adapters.some((existing) => existing.id === adapter.id)) {
      throw new Error(`Adapter "${adapter.id}" is already registered.`);
    }
    this.adapters.push(adapter);
    return this;
  }

  /** First adapter that claims the page, else the generic one. */
  resolve(ctx: DetectionContext): StoreAdapter {
    for (const adapter of this.adapters) {
      try {
        if (adapter.canHandle(ctx)) return adapter;
      } catch {
        // A broken adapter must never take the pipeline down with it.
        continue;
      }
    }
    return this.fallback;
  }

  list(): StoreAdapter[] {
    return [...this.adapters, this.fallback];
  }
}

/**
 * The registry used at runtime.
 *
 * Order matters only in that the first adapter claiming a page wins; the
 * adapters here match on distinct hostnames, so the order is alphabetical for
 * readability rather than precedence.
 *
 * Every store *not* listed here still works — it goes through the generic
 * pipeline, which is the same pipeline these adapters are enhancing.
 */
export const registry = new StoreRegistry();

registry
  .register(AdidasAdapter)
  .register(AjioAdapter)
  .register(AmazonAdapter)
  .register(HmAdapter)
  .register(MyntraAdapter)
  .register(NikeAdapter)
  .register(NykaaAdapter)
  .register(UniqloAdapter)
  .register(ZaraAdapter);
