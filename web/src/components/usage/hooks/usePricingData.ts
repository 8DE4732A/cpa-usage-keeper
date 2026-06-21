import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ApiError,
  deletePricing,
  fetchOpenRouterModels,
  fetchPricing,
  fetchUsedModels,
  syncOpenRouterPrices,
  updatePricing,
} from '@/lib/api';
import type { OpenRouterModelPrice } from '@/lib/types';
import { useNotificationStore } from '@/stores';
import { loadModelPrices, saveModelPrices, extractModelKey, type ModelPrice } from '@/utils/usage';

export interface UsePricingDataOptions {
  onAuthRequired?: () => void;
  enabled?: boolean;
}

export interface UsePricingDataReturn {
  modelNames: string[];
  modelPrices: Record<string, ModelPrice>;
  loading: boolean;
  error: string;
  lastRefreshedAt: Date | null;
  loadPricing: () => Promise<void>;
  setModelPrices: (prices: Record<string, ModelPrice>) => Promise<void>;
  openRouterPrices: Record<string, OpenRouterModelPrice>;
  syncing: boolean;
  syncOpenRouter: () => Promise<void>;
}

const pricingToModelPrice = (entry: {
  model: string;
  prompt_price_per_1m: number;
  completion_price_per_1m: number;
  cache_price_per_1m: number;
}): ModelPrice => ({
  prompt: entry.prompt_price_per_1m,
  completion: entry.completion_price_per_1m,
  cache: entry.cache_price_per_1m,
});

export function usePricingData(options: UsePricingDataOptions = {}): UsePricingDataReturn {
  const { onAuthRequired, enabled = true } = options;
  const { t } = useTranslation();
  const { showNotification } = useNotificationStore();
  const [modelNames, setModelNames] = useState<string[]>([]);
  const [modelPrices, setModelPricesState] = useState<Record<string, ModelPrice>>(() => loadModelPrices());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [openRouterPrices, setOpenRouterPrices] = useState<Record<string, OpenRouterModelPrice>>({});
  const [syncing, setSyncing] = useState(false);
  const requestControllerRef = useRef<AbortController | null>(null);

  const loadPricing = useCallback(async () => {
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;

    setLoading(true);
    setError('');

    try {
      // Fetch DB-dependent data first — these compete for pool_size=1.
      const [pricingResponse, usedModelsResponse] = await Promise.all([
        fetchPricing(controller.signal),
        fetchUsedModels(controller.signal),
      ]);
      if (requestControllerRef.current !== controller) {
        return;
      }
      const prices = Object.fromEntries(
        pricingResponse.pricing.map((entry) => [entry.model, pricingToModelPrice(entry)])
      );
      saveModelPrices(prices);
      setModelPricesState(prices);
      setModelNames(usedModelsResponse.models);

      // Fetch OpenRouter models lazily — they are read-only cache and
      // only used for display hints (badge / reference price).  By fetching
      // them *after* the DB calls we avoid competing for pool_size=1 when
      // the real DB work hasn't finished yet.
      fetchOpenRouterModels(controller.signal)
        .then((orResponse) => {
          if (requestControllerRef.current !== controller) return;
          const orIndex: Record<string, OpenRouterModelPrice> = {};
          for (const m of orResponse.models) {
            orIndex[m.id] = m;
          }
          setOpenRouterPrices(orIndex);
        })
        .catch(() => {
          // OpenRouter is optional — silently ignore failures.
        });

      setLastRefreshedAt(new Date());
    } catch (error) {
      if (controller.signal.aborted) {
        return;
      }
      if (error instanceof ApiError && error.status === 401) {
        onAuthRequired?.();
        return;
      }
      setModelPricesState(loadModelPrices());
      setError(error instanceof Error ? error.message : 'Failed to load pricing');
    } finally {
      if (requestControllerRef.current === controller) {
        setLoading(false);
        requestControllerRef.current = null;
      }
    }
  }, [onAuthRequired]);

  useEffect(() => {
    if (!enabled) {
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
      setLoading(false);
      return;
    }
    void loadPricing();
    return () => {
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
    };
  }, [enabled, loadPricing]);

  const setModelPrices = useCallback(async (prices: Record<string, ModelPrice>) => {
    const previousPrices = modelPrices;
    setModelPricesState(prices);
    saveModelPrices(prices);

    try {
      // Only ask the backend for models that *actually changed* (new, or different values).
      const changedModels = Object.entries(prices).filter(([model, pricing]) => {
        const prev = previousPrices[model];
        return !prev
          || prev.prompt !== pricing.prompt
          || prev.completion !== pricing.completion
          || prev.cache !== pricing.cache;
      });

      // Models that existed before but are no longer in the set → delete them.
      const deletedModels = Object.keys(previousPrices)
        .filter((model) => !(model in prices));

      await Promise.all([
        ...changedModels.map(([model, pricing]) =>
          updatePricing(model, {
            prompt_price_per_1m: pricing.prompt,
            completion_price_per_1m: pricing.completion,
            cache_price_per_1m: pricing.cache,
          })
        ),
        ...deletedModels.map((model) => deletePricing(model)),
      ]);
      setLastRefreshedAt(new Date());
    } catch (error) {
      setModelPricesState(previousPrices);
      saveModelPrices(previousPrices);
      if (error instanceof ApiError && error.status === 401) {
        onAuthRequired?.();
        return;
      }
      const message = error instanceof Error ? error.message : '';
      showNotification(
        `${t('notification.upload_failed')}${message ? `: ${message}` : ''}`,
        'error'
      );
    }
  }, [modelPrices, onAuthRequired, showNotification, t]);

  const syncOpenRouter = useCallback(async () => {
    setSyncing(true);
    try {
      const result = await syncOpenRouterPrices();
      showNotification(
        `OpenRouter 同步完成: ${result.matched} 个模型匹配, ${result.created} 个新创建`,
        'success'
      );
      // Reload pricing data after sync
      await loadPricing();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        onAuthRequired?.();
        return;
      }
      const message = error instanceof Error ? error.message : '';
      showNotification(
        `OpenRouter 同步失败${message ? `: ${message}` : ''}`,
        'error'
      );
    } finally {
      setSyncing(false);
    }
  }, [showNotification, loadPricing, onAuthRequired]);

  return {
    modelNames,
    modelPrices,
    loading,
    error,
    lastRefreshedAt,
    loadPricing,
    setModelPrices,
    openRouterPrices,
    syncing,
    syncOpenRouter,
  };
}
