import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Select, type SelectOption } from '@/components/ui/Select';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import type { NotificationChannel, NotificationRule } from '@/lib/types';
import styles from '@/pages/UsagePage.module.scss';

/* ── Helper sub-components ─────────────────────────────────────────────────── */

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className={styles.sectionTitleBlock}>
      <span className={styles.sectionEyebrow}>{eyebrow}</span>
      <h3 className={styles.sectionTitle}>{title}</h3>
    </div>
  );
}

const fmtTime = (iso: string | null | undefined): string => {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
};

/* ── Props ──────────────────────────────────────────────────────────────────── */

export interface NotificationSettingsCardProps {
  channels: NotificationChannel[];
  rules: NotificationRule[];
  loading: boolean;
  onCreateChannel: (data: {
    name: string;
    channel_type: string;
    config: { webhook_url: string };
    enabled?: boolean;
  }) => Promise<void>;
  onUpdateChannel: (
    id: number,
    data: {
      name?: string;
      channel_type?: string;
      config?: { webhook_url: string };
      enabled?: boolean;
    }
  ) => Promise<void>;
  onDeleteChannel: (id: number) => Promise<void>;
  onTestWebhook: (id: number) => Promise<boolean>;
  onCreateRule: (data: {
    name: string;
    channel_id: number;
    rule_type: string;
    config: { threshold?: number; window_minutes: number };
    enabled?: boolean;
    cooldown_minutes?: number;
  }) => Promise<void>;
  onUpdateRule: (
    id: number,
    data: {
      name?: string;
      channel_id?: number;
      rule_type?: string;
      config?: { threshold?: number; window_minutes: number };
      enabled?: boolean;
      cooldown_minutes?: number;
    }
  ) => Promise<void>;
  onDeleteRule: (id: number) => Promise<void>;
}

/* ── Main Component ─────────────────────────────────────────────────────────── */

export function NotificationSettingsCard({
  channels,
  rules,
  loading,
  onCreateChannel,
  onUpdateChannel,
  onDeleteChannel,
  onTestWebhook,
  onCreateRule,
  onUpdateRule,
  onDeleteRule,
}: NotificationSettingsCardProps) {
  const { t } = useTranslation();

  // ── Channel modal state ──────────────────────────────────────────────────
  const [channelModal, setChannelModal] = useState<{
    mode: 'add' | 'edit';
    id?: number;
  } | null>(null);
  const [channelName, setChannelName] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [channelEnabled, setChannelEnabled] = useState(true);
  const [testingId, setTestingId] = useState<number | null>(null);

  // ── Rule modal state ────────────────────────────────────────────────────
  const [ruleModal, setRuleModal] = useState<{
    mode: 'add' | 'edit';
    id?: number;
  } | null>(null);
  const [ruleName, setRuleName] = useState('');
  const [ruleChannelId, setRuleChannelId] = useState<number>(0);
  const [ruleType, setRuleType] = useState<'token_threshold' | 'connection_failure'>('token_threshold');
  const [ruleThreshold, setRuleThreshold] = useState('');
  const [ruleWindow, setRuleWindow] = useState('60');
  const [ruleCooldown, setRuleCooldown] = useState('30');
  const [ruleEnabled, setRuleEnabled] = useState(true);

  // ── Open channel modal ───────────────────────────────────────────────────
  const openAddChannel = () => {
    setChannelModal({ mode: 'add' });
    setChannelName('');
    setWebhookUrl('');
    setChannelEnabled(true);
  };

  const openEditChannel = (ch: NotificationChannel) => {
    setChannelModal({ mode: 'edit', id: ch.id });
    setChannelName(ch.name);
    setWebhookUrl(ch.config.webhook_url);
    setChannelEnabled(ch.enabled);
  };

  const closeChannelModal = () => setChannelModal(null);

  const handleSaveChannel = async () => {
    if (!channelName.trim() || !webhookUrl.trim()) return;
    if (channelModal?.mode === 'add') {
      await onCreateChannel({
        name: channelName.trim(),
        channel_type: 'wecom_bot',
        config: { webhook_url: webhookUrl.trim() },
        enabled: channelEnabled,
      });
    } else if (channelModal?.mode === 'edit' && channelModal.id) {
      await onUpdateChannel(channelModal.id, {
        name: channelName.trim(),
        config: { webhook_url: webhookUrl.trim() },
        enabled: channelEnabled,
      });
    }
    closeChannelModal();
  };

  // ── Open rule modal ──────────────────────────────────────────────────────
  const openAddRule = () => {
    setRuleModal({ mode: 'add' });
    setRuleName('');
    setRuleChannelId(channels.length > 0 ? channels[0].id : 0);
    setRuleType('token_threshold');
    setRuleThreshold('');
    setRuleWindow('60');
    setRuleCooldown('30');
    setRuleEnabled(true);
  };

  const openEditRule = (r: NotificationRule) => {
    setRuleModal({ mode: 'edit', id: r.id });
    setRuleName(r.name);
    setRuleChannelId(r.channel_id);
    setRuleType(r.rule_type);
    setRuleThreshold(r.config.threshold?.toString() ?? '');
    setRuleWindow(r.config.window_minutes.toString());
    setRuleCooldown(r.cooldown_minutes.toString());
    setRuleEnabled(r.enabled);
  };

  const closeRuleModal = () => setRuleModal(null);

  const handleSaveRule = async () => {
    if (!ruleName.trim() || !ruleChannelId) return;
    const config: { threshold?: number; window_minutes: number } = {
      window_minutes: parseInt(ruleWindow, 10) || 60,
    };
    if (ruleType === 'token_threshold') {
      config.threshold = parseInt(ruleThreshold, 10) || 0;
    }
    if (ruleModal?.mode === 'add') {
      await onCreateRule({
        name: ruleName.trim(),
        channel_id: ruleChannelId,
        rule_type: ruleType,
        config,
        enabled: ruleEnabled,
        cooldown_minutes: parseInt(ruleCooldown, 10) || 30,
      });
    } else if (ruleModal?.mode === 'edit' && ruleModal.id) {
      await onUpdateRule(ruleModal.id, {
        name: ruleName.trim(),
        channel_id: ruleChannelId,
        rule_type: ruleType,
        config,
        enabled: ruleEnabled,
        cooldown_minutes: parseInt(ruleCooldown, 10) || 30,
      });
    }
    closeRuleModal();
  };

  // ── Test webhook ─────────────────────────────────────────────────────────
  const handleTest = async (id: number) => {
    setTestingId(id);
    await onTestWebhook(id);
    setTestingId(null);
  };

  // ── Derived data ─────────────────────────────────────────────────────────
  const enabledChannels = useMemo(() => channels.filter((c) => c.enabled), [channels]);
  const channelOptions: SelectOption[] = useMemo(
    () => [
      { value: '', label: t('usage_stats.select_channel') },
      ...channels.map((c) => ({
        value: String(c.id),
        label: c.name || `#${c.id}`,
      })),
    ],
    [channels, t],
  );
  const ruleTypeOptions: SelectOption[] = useMemo(
    () => [
      { value: 'token_threshold', label: t('usage_stats.token_threshold_rule') },
      { value: 'connection_failure', label: t('usage_stats.connection_failure_rule') },
    ],
    [t],
  );

  /* ── Render ───────────────────────────────────────────────────────────── */
  return (
    <Card
      title={
        <SectionTitle
          eyebrow={t('usage_stats.notification_channels')}
          title={t('usage_stats.tab_notifications')}
        />
      }
      className={styles.detailsFixedCard}
    >
      {loading ? (
        <div className={styles.loadingContainer}>
          <LoadingSpinner size={24} />
        </div>
      ) : (
        <>
          {/* ── Notification Channels ──────────────────────────────── */}
          <div className={styles.notifySection}>
            <div className={styles.notifySectionHeader}>
              <h4 className={styles.notifySectionTitle}>
                {t('usage_stats.notification_channels')}
              </h4>
              <Button variant="primary" size="sm" onClick={openAddChannel}>
                {t('usage_stats.add_channel')}
              </Button>
            </div>

            {channels.length === 0 ? (
              <div className={styles.hint}>{t('usage_stats.channel_empty')}</div>
            ) : (
              <div className={styles.notifyList}>
                {channels.map((ch) => (
                  <div key={ch.id} className={styles.notifyItem}>
                    <div className={styles.notifyItemInfo}>
                      <span className={styles.notifyItemName}>{ch.name}</span>
                      <span className={styles.channelTypeBadge}>
                        {t('usage_stats.wecom_webhook')}
                      </span>
                      <span className={styles.notifyItemMeta}>
                        {ch.config.webhook_url?.slice(0, 60)}...
                      </span>
                      <span className={styles.notifyItemStatus}>
                        {ch.enabled ? '✓' : '✗'}
                      </span>
                    </div>
                    <div className={styles.notifyItemActions}>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleTest(ch.id)}
                        loading={testingId === ch.id}
                        disabled={testingId === ch.id}
                      >
                        {t('usage_stats.test_webhook')}
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => openEditChannel(ch)}
                      >
                        {t('common.edit')}
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => onDeleteChannel(ch.id)}
                      >
                        {t('common.delete')}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Notification Rules ────────────────────────────────── */}
          <div className={styles.notifySection}>
            <div className={styles.notifySectionHeader}>
              <h4 className={styles.notifySectionTitle}>
                {t('usage_stats.notification_rules')}
              </h4>
              <Button
                variant="primary"
                size="sm"
                onClick={openAddRule}
                disabled={enabledChannels.length === 0}
              >
                {t('usage_stats.add_rule')}
              </Button>
            </div>

            {rules.length === 0 ? (
              <div className={styles.hint}>{t('usage_stats.rule_empty')}</div>
            ) : (
              <div className={styles.notifyList}>
                {rules.map((r) => {
                  const summaryKey =
                    r.rule_type === 'token_threshold'
                      ? 'rule_trigger_summary_token'
                      : 'rule_trigger_summary_failure';
                  return (
                    <div key={r.id} className={styles.notifyItem}>
                      <div className={styles.notifyItemInfo}>
                        <span className={styles.notifyItemName}>{r.name}</span>
                        <span className={styles.channelTypeBadge}>
                          {r.rule_type === 'token_threshold'
                            ? t('usage_stats.token_threshold_rule')
                            : t('usage_stats.connection_failure_rule')}
                        </span>
                        <span className={styles.notifyItemMeta}>
                          {r.rule_type === 'token_threshold'
                            ? t(summaryKey, {
                                type: 'tokens',
                                threshold: r.config.threshold?.toLocaleString() ?? 0,
                                window: r.config.window_minutes,
                              })
                            : t(summaryKey, {
                                window: r.config.window_minutes,
                              })}
                        </span>
                        <span className={styles.notifyItemMeta}>
                          {t('usage_stats.last_notified')}:{' '}
                          {r.last_notified_at
                            ? fmtTime(r.last_notified_at)
                            : t('usage_stats.never_notified')}
                        </span>
                        <span className={styles.notifyItemStatus}>
                          {r.enabled ? '✓' : '✗'}
                        </span>
                        {r.channel_name && (
                          <span className={styles.notifyItemChannel}>
                            → {r.channel_name}
                          </span>
                        )}
                      </div>
                      <div className={styles.notifyItemActions}>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => openEditRule(r)}
                        >
                          {t('common.edit')}
                        </Button>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => onDeleteRule(r.id)}
                        >
                          {t('common.delete')}
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Channel Add/Edit Modal ──────────────────────────────────── */}
      <Modal
        open={channelModal !== null}
        title={
          channelModal?.mode === 'add'
            ? t('usage_stats.add_channel')
            : t('usage_stats.edit_channel')
        }
        onClose={closeChannelModal}
        footer={
          <div className={styles.priceActions}>
            <Button variant="secondary" onClick={closeChannelModal}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              onClick={handleSaveChannel}
              disabled={!channelName.trim() || !webhookUrl.trim()}
            >
              {t('common.save')}
            </Button>
          </div>
        }
        width={480}
      >
        <div className={styles.editModalBody}>
          <div className={styles.formField}>
            <label>{t('usage_stats.channel_name')}</label>
            <Input
              value={channelName}
              onChange={(e) => setChannelName(e.target.value)}
              placeholder={t('usage_stats.channel_name')}
            />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.channel_type')}</label>
            <Input value={t('usage_stats.wecom_webhook')} disabled />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.webhook_url')}</label>
            <Input
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder={t('usage_stats.webhook_url_placeholder')}
            />
          </div>
          <div className={styles.formField}>
            <label>
              <input
                type="checkbox"
                checked={channelEnabled}
                onChange={(e) => setChannelEnabled(e.target.checked)}
              />{' '}
              {t('usage_stats.enabled')}
            </label>
          </div>
        </div>
      </Modal>

      {/* ── Rule Add/Edit Modal ────────────────────────────────────── */}
      <Modal
        open={ruleModal !== null}
        title={
          ruleModal?.mode === 'add'
            ? t('usage_stats.add_rule')
            : t('usage_stats.edit_rule')
        }
        onClose={closeRuleModal}
        footer={
          <div className={styles.priceActions}>
            <Button variant="secondary" onClick={closeRuleModal}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              onClick={handleSaveRule}
              disabled={!ruleName.trim() || !ruleChannelId}
            >
              {t('common.save')}
            </Button>
          </div>
        }
        width={480}
      >
        <div className={styles.editModalBody}>
          <div className={styles.formField}>
            <label>{t('usage_stats.rule_name')}</label>
            <Input
              value={ruleName}
              onChange={(e) => setRuleName(e.target.value)}
              placeholder={t('usage_stats.rule_name')}
            />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.rule_type')}</label>
            <Select
              value={ruleType}
              options={ruleTypeOptions}
              onChange={(val) => setRuleType(val as 'token_threshold' | 'connection_failure')}
            />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.select_channel')}</label>
            <Select
              value={String(ruleChannelId)}
              options={channelOptions}
              onChange={(val) => setRuleChannelId(Number(val))}
            />
          </div>
          {ruleType === 'token_threshold' && (
            <div className={styles.formField}>
              <label>
                {t('usage_stats.threshold')} ({t('usage_stats.tokens_unit')})
              </label>
              <Input
                type="number"
                value={ruleThreshold}
                onChange={(e) => setRuleThreshold(e.target.value)}
                placeholder="1000000"
                min="0"
                step="1"
              />
            </div>
          )}
          <div className={styles.formField}>
            <label>{t('usage_stats.window_minutes')}</label>
            <Input
              type="number"
              value={ruleWindow}
              onChange={(e) => setRuleWindow(e.target.value)}
              placeholder="60"
              min="1"
              step="1"
            />
          </div>
          <div className={styles.formField}>
            <label>{t('usage_stats.cooldown_minutes')}</label>
            <Input
              type="number"
              value={ruleCooldown}
              onChange={(e) => setRuleCooldown(e.target.value)}
              placeholder="30"
              min="1"
              step="1"
            />
          </div>
          <div className={styles.formField}>
            <label>
              <input
                type="checkbox"
                checked={ruleEnabled}
                onChange={(e) => setRuleEnabled(e.target.checked)}
              />{' '}
              {t('usage_stats.enabled')}
            </label>
          </div>
        </div>
      </Modal>
    </Card>
  );
}
