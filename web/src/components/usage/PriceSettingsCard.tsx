import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select, type SelectOption } from '@/components/ui/Select';
import { IconCheck, IconRefreshCw } from '@/components/ui/icons';
import type { OpenRouterModelPrice } from '@/lib/types';
import { extractModelKey, type ModelPrice } from '@/utils/usage';
import styles from '@/pages/UsagePage.module.scss';

const formatDisplayName = (value: string): string => {
  const normalized = value.trim();
  if (!normalized) return '-';
  return normalized;
};

/**
 * Build a key-indexed lookup for O(1) OR price matching.
 * Keys are both the full id and the last /-segment.
 */
function buildORIndex(orPrices: Record<string, OpenRouterModelPrice>): Record<string, OpenRouterModelPrice> {
  const idx: Record<string, OpenRouterModelPrice> = {};
  for (const m of Object.values(orPrices)) {
    idx[m.id] = m;
    idx[`__key__${extractModelKey(m.id)}`] = m;
  }
  return idx;
}

/** O(1) lookup: try exact id, then key prefix. */
function findMatchingORPrice(
  modelName: string,
  idx: Record<string, OpenRouterModelPrice>,
): OpenRouterModelPrice | undefined {
  return idx[modelName] ?? idx[`__key__${extractModelKey(modelName)}`];
}

export interface PriceSettingsCardProps {
  modelNames: string[];
  modelPrices: Record<string, ModelPrice>;
  onPricesChange: (prices: Record<string, ModelPrice>) => void;
  loading?: boolean;
  openRouterPrices?: Record<string, OpenRouterModelPrice>;
  onSyncOpenRouter?: () => Promise<void>;
  syncing?: boolean;
}

function PriceSettingsTitle({ title, subtitle, eyebrow }: { title: string; subtitle: string; eyebrow: string }) {
  return (
    <div className={styles.sectionTitleBlock}>
      <span className={styles.sectionEyebrow}>{eyebrow}</span>
      <h3 className={styles.sectionTitle}>{title}</h3>
      <p className={styles.sectionSubtitle}>{subtitle}</p>
    </div>
  );
}

const parsePriceValue = (value: string): number | null => {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
};

export const buildPricingModelOptions = (
  modelNames: string[],
  modelPrices: Record<string, ModelPrice>,
  openRouterPrices: Record<string, OpenRouterModelPrice> | undefined,
  placeholder: string,
  configuredSuffix: React.ReactNode,
  configuredLabel: string,
  orSuffix: React.ReactNode,
  orLabel: string,
): SelectOption[] => {
  const configuredModels = new Set(Object.keys(modelPrices));
  const sortedModelNames = [...modelNames].sort((left, right) => {
    const leftConfigured = configuredModels.has(left);
    const rightConfigured = configuredModels.has(right);
    if (leftConfigured !== rightConfigured) return leftConfigured ? 1 : -1;
    return formatDisplayName(left).localeCompare(formatDisplayName(right));
  });

  return [
    { value: '', label: placeholder },
    ...sortedModelNames.map((name) => {
      const hasOR = !!(openRouterPrices && findMatchingORPrice(name, openRouterPrices));
      let suffix: React.ReactNode | undefined;
      let suffixLabel: string | undefined;
      if (configuredModels.has(name)) {
        suffix = configuredSuffix;
        suffixLabel = configuredLabel;
      } else if (hasOR) {
        suffix = orSuffix;
        suffixLabel = orLabel;
      }
      return {
        value: name,
        label: formatDisplayName(name),
        suffix,
        suffixAriaLabel: suffixLabel,
      };
    }),
  ];
};

/** Format a price value for display, handling null. */
const fmt = (v: number | null | undefined, fallback = '-'): string => {
  if (v == null) return fallback;
  return `$${v.toFixed(4)}/1M`;
};

export function PriceSettingsCard({
  modelNames,
  modelPrices,
  onPricesChange,
  loading = false,
  openRouterPrices = {},
  onSyncOpenRouter,
  syncing = false,
}: PriceSettingsCardProps) {
  const { t } = useTranslation();

  // O(1) OR index built once per openRouterPrices change
  const orIndex = useMemo(() => buildORIndex(openRouterPrices), [openRouterPrices]);

  // Add form state
  const [selectedModel, setSelectedModel] = useState('');
  const [promptPrice, setPromptPrice] = useState('');
  const [completionPrice, setCompletionPrice] = useState('');
  const [cachePrice, setCachePrice] = useState('');

  // Edit modal state
  const [editModel, setEditModel] = useState<string | null>(null);
  const [editPrompt, setEditPrompt] = useState('');
  const [editCompletion, setEditCompletion] = useState('');
  const [editCache, setEditCache] = useState('');

  const handleSavePrice = () => {
    if (!selectedModel) return;
    const prompt = parsePriceValue(promptPrice);
    const completion = parsePriceValue(completionPrice);
    const cache = cachePrice.trim() === '' ? prompt : parsePriceValue(cachePrice);
    if (prompt === null || completion === null || cache === null) return;
    const newPrices = { ...modelPrices, [selectedModel]: { prompt, completion, cache } };
    onPricesChange(newPrices);
    setSelectedModel('');
    setPromptPrice('');
    setCompletionPrice('');
    setCachePrice('');
  };

  /** Reset custom prices to 0 so the effective price falls back to OR. */
  const handleResetPrice = (model: string) => {
    const newPrices = { ...modelPrices, [model]: { prompt: 0, completion: 0, cache: 0 } };
    onPricesChange(newPrices);
  };

  const handleOpenEdit = (model: string) => {
    const price = modelPrices[model];
    const orMatch = findMatchingORPrice(model, orIndex);
    const hasUserPrice = price && price.prompt !== 0;
    setEditModel(model);
    setEditPrompt((hasUserPrice ? price.prompt : (orMatch?.prompt_price_per_1m ?? 0)).toString());
    setEditCompletion((hasUserPrice ? price.completion : (orMatch?.completion_price_per_1m ?? 0)).toString());
    setEditCache((hasUserPrice ? price.cache : (orMatch?.cache_price_per_1m ?? 0)).toString());
  };

  const handleSaveEdit = () => {
    if (!editModel) return;
    const prompt = parsePriceValue(editPrompt);
    const completion = parsePriceValue(editCompletion);
    const cache = editCache.trim() === '' ? prompt : parsePriceValue(editCache);
    if (prompt === null || completion === null || cache === null) return;
    const newPrices = { ...modelPrices, [editModel]: { prompt, completion, cache } };
    onPricesChange(newPrices);
    setEditModel(null);
  };

  /** When user selects a model, pre-fill from OR if no user price set. */
  const handleModelSelect = (value: string) => {
    setSelectedModel(value);
    const price = modelPrices[value];
    if (price && price.prompt !== 0) {
      setPromptPrice(price.prompt.toString());
      setCompletionPrice(price.completion.toString());
      setCachePrice(price.cache.toString());
    } else {
      const orMatch = findMatchingORPrice(value, orIndex);
      if (orMatch) {
        setPromptPrice((orMatch.prompt_price_per_1m ?? 0).toString());
        setCompletionPrice((orMatch.completion_price_per_1m ?? 0).toString());
        setCachePrice((orMatch.cache_price_per_1m ?? 0).toString());
      } else {
        setPromptPrice('');
        setCompletionPrice('');
        setCachePrice('');
      }
    }
  };

  const options = useMemo(
    () =>
      buildPricingModelOptions(
        modelNames,
        modelPrices,
        orIndex,
        t('usage_stats.model_price_select_placeholder'),
        <IconCheck size={10} />,
        t('usage_stats.model_price_configured'),
        <IconRefreshCw size={10} />,
        t('usage_stats.openrouter_available'),
      ),
    [modelNames, modelPrices, orIndex, t],
  );

  return (
    <Card
      title={
        <PriceSettingsTitle
          eyebrow={t('usage_stats.model_price_settings_eyebrow')}
          title={t('usage_stats.model_price_settings_title')}
          subtitle={t('usage_stats.model_price_settings_subtitle')}
        />
      }
      className={styles.detailsFixedCard}
    >
      <div className={styles.pricingSection}>
        {loading && modelNames.length === 0 && Object.keys(modelPrices).length === 0 ? (
          <div className={styles.hint}>{t('common.loading')}</div>
        ) : (
          <>
            <div className={styles.priceForm}>
              <div className={styles.formRow}>
                <div className={styles.formField}>
                  <label>{t('usage_stats.model_name')}</label>
                  <Select
                    value={selectedModel}
                    options={options}
                    onChange={handleModelSelect}
                    placeholder={t('usage_stats.model_price_select_placeholder')}
                  />
                </div>
                <div className={styles.formField}>
                  <label>{t('usage_stats.model_price_prompt')} ($/1M)</label>
                  <Input
                    type="number"
                    value={promptPrice}
                    onChange={(e) => setPromptPrice(e.target.value)}
                    placeholder="0.00"
                    step="0.0001"
                  />
                </div>
                <div className={styles.formField}>
                  <label>{t('usage_stats.model_price_completion')} ($/1M)</label>
                  <Input
                    type="number"
                    value={completionPrice}
                    onChange={(e) => setCompletionPrice(e.target.value)}
                    placeholder="0.00"
                    step="0.0001"
                  />
                </div>
                <div className={styles.formField}>
                  <label>{t('usage_stats.model_price_cache')} ($/1M)</label>
                  <Input
                    type="number"
                    value={cachePrice}
                    onChange={(e) => setCachePrice(e.target.value)}
                    placeholder="0.00"
                    step="0.0001"
                  />
                </div>
                <Button variant="primary" onClick={handleSavePrice} disabled={!selectedModel}>
                  {t('common.save')}
                </Button>
              </div>
            </div>

            {/* Sync OpenRouter button */}
            {onSyncOpenRouter && (
              <div className={styles.orSyncRow}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onSyncOpenRouter}
                  disabled={syncing}
                  className={styles.orSyncButton}
                >
                  <IconRefreshCw size={12} />
                  <span>
                    {syncing
                      ? t('usage_stats.syncing_openrouter')
                      : t('usage_stats.sync_openrouter_prices')}
                  </span>
                </Button>
              </div>
            )}

            <div className={styles.pricesList}>
              <h4 className={styles.pricesTitle}>{t('usage_stats.saved_prices')}</h4>
              {Object.keys(modelPrices).length > 0 ? (
                <div className={styles.pricesGrid}>
                  {Object.entries(modelPrices).map(([model, price]) => {
                    const orMatch = findMatchingORPrice(model, orIndex);
                    const isUserSet = price.prompt !== 0;
                    return (
                      <div key={model} className={styles.priceItem}>
                        <div className={styles.priceInfo}>
                          <span className={styles.priceModel}>
                            {formatDisplayName(model)}
                            {isUserSet && (
                              <span className={styles.orBadgeCustom}>
                                {t('usage_stats.custom_price')}
                              </span>
                            )}
                            {!isUserSet && orMatch && (
                              <span className={styles.orBadge}>
                                {t('usage_stats.openrouter_price')}
                              </span>
                            )}
                          </span>
                          <div className={styles.priceMeta}>
                            <span>
                              {t('usage_stats.model_price_prompt')}: ${(isUserSet ? price.prompt : (orMatch?.prompt_price_per_1m ?? 0)).toFixed(4)}/1M
                            </span>
                            <span>
                              {t('usage_stats.model_price_completion')}: ${(isUserSet ? price.completion : (orMatch?.completion_price_per_1m ?? 0)).toFixed(4)}/1M
                            </span>
                            <span>
                              {t('usage_stats.model_price_cache')}: ${(isUserSet ? price.cache : (orMatch?.cache_price_per_1m ?? 0)).toFixed(4)}/1M
                            </span>
                          </div>
                          {/* Show OpenRouter reference price when user overrode */}
                          {isUserSet && orMatch && (
                            <div className={styles.orReferencePrice}>
                              <span className={styles.orReferenceLabel}>
                                {t('usage_stats.openrouter_reference')}:
                              </span>{' '}
                              {fmt(orMatch.prompt_price_per_1m)} / {fmt(orMatch.completion_price_per_1m)} /{' '}
                              {fmt(orMatch.cache_price_per_1m)}
                            </div>
                          )}
                        </div>
                        <div className={styles.priceActions}>
                          <Button variant="secondary" size="sm" onClick={() => handleOpenEdit(model)}>
                            {t('common.edit')}
                          </Button>
                          {isUserSet && (
                            <Button variant="danger" size="sm" onClick={() => handleResetPrice(model)}>
                              {t('usage_stats.reset_price')}
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className={styles.hint}>{t('usage_stats.model_price_empty')}</div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Edit Modal */}
      <Modal
        open={editModel !== null}
        title={formatDisplayName(editModel ?? '')}
        onClose={() => setEditModel(null)}
        footer={
          <div className={styles.priceActions}>
            <Button variant="secondary" onClick={() => setEditModel(null)}>
              {t('common.cancel')}
            </Button>
            <Button variant="primary" onClick={handleSaveEdit}>
              {t('common.save')}
            </Button>
          </div>
        }
        width={420}
      >
        <div className={styles.editModalBody}>
          <div className={styles.formField}>
            <label>{t('usage_stats.model_price_prompt')} ($/1M)</label>
            <Input
              type="number"
              value={editPrompt}
              onChange={(e) => setEditPrompt(e.target.value)}
              placeholder="0.00"
              step="0.0001"
            />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.model_price_completion')} ($/1M)</label>
            <Input
              type="number"
              value={editCompletion}
              onChange={(e) => setEditCompletion(e.target.value)}
              placeholder="0.00"
              step="0.0001"
            />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.model_price_cache')} ($/1M)</label>
            <Input
              type="number"
              value={editCache}
              onChange={(e) => setEditCache(e.target.value)}
              placeholder="0.00"
              step="0.0001"
            />
          </div>
        </div>
      </Modal>
    </Card>
  );
}
