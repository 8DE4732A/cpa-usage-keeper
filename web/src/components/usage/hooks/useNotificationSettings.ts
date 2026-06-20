import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ApiError,
  createNotificationChannel,
  createNotificationRule,
  deleteNotificationChannel,
  deleteNotificationRule,
  fetchNotificationChannels,
  fetchNotificationRules,
  testNotificationWebhook,
  updateNotificationChannel,
  updateNotificationRule,
} from '@/lib/api';
import type { NotificationChannel, NotificationRule } from '@/lib/types';
import { useNotificationStore } from '@/stores';

export interface UseNotificationSettingsOptions {
  onAuthRequired?: () => void;
  enabled?: boolean;
}

export interface UseNotificationSettingsReturn {
  channels: NotificationChannel[];
  rules: NotificationRule[];
  loading: boolean;
  refresh: () => Promise<void>;
  createChannel: (data: {
    name: string;
    channel_type: string;
    config: { webhook_url: string };
    enabled?: boolean;
  }) => Promise<void>;
  updateChannel: (
    id: number,
    data: {
      name?: string;
      channel_type?: string;
      config?: { webhook_url: string };
      enabled?: boolean;
    }
  ) => Promise<void>;
  deleteChannel: (id: number) => Promise<void>;
  testWebhook: (id: number) => Promise<boolean>;
  createRule: (data: {
    name: string;
    channel_id: number;
    rule_type: string;
    config: { threshold?: number; window_minutes: number };
    enabled?: boolean;
    cooldown_minutes?: number;
  }) => Promise<void>;
  updateRule: (
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
  deleteRule: (id: number) => Promise<void>;
}

export function useNotificationSettings(
  options: UseNotificationSettingsOptions = {}
): UseNotificationSettingsReturn {
  const { onAuthRequired, enabled = true } = options;
  const { t } = useTranslation();
  const { showNotification } = useNotificationStore();
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [rules, setRules] = useState<NotificationRule[]>([]);
  const [loading, setLoading] = useState(false);
  const requestControllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    requestControllerRef.current?.abort();
    const controller = new AbortController();
    requestControllerRef.current = controller;

    setLoading(true);

    try {
      const [channelsRes, rulesRes] = await Promise.all([
        fetchNotificationChannels(controller.signal),
        fetchNotificationRules(controller.signal),
      ]);
      if (requestControllerRef.current !== controller) {
        return;
      }
      setChannels(channelsRes.channels);
      setRules(rulesRes.rules);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) {
        onAuthRequired?.();
        return;
      }
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
    void refresh();
    return () => {
      requestControllerRef.current?.abort();
      requestControllerRef.current = null;
    };
  }, [enabled, refresh]);

  const createChannel = useCallback(
    async (data: {
      name: string;
      channel_type: string;
      config: { webhook_url: string };
      enabled?: boolean;
    }) => {
      try {
        await createNotificationChannel(data);
        await refresh();
        showNotification(t('common.success'), 'success');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthRequired?.();
          return;
        }
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `创建渠道失败${message ? `: ${message}` : ''}`,
          'error'
        );
      }
    },
    [refresh, onAuthRequired, showNotification, t]
  );

  const updateChannel = useCallback(
    async (
      id: number,
      data: {
        name?: string;
        channel_type?: string;
        config?: { webhook_url: string };
        enabled?: boolean;
      }
    ) => {
      try {
        await updateNotificationChannel(id, data);
        await refresh();
        showNotification(t('common.success'), 'success');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthRequired?.();
          return;
        }
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `更新渠道失败${message ? `: ${message}` : ''}`,
          'error'
        );
      }
    },
    [refresh, onAuthRequired, showNotification, t]
  );

  const deleteChannel = useCallback(
    async (id: number) => {
      try {
        await deleteNotificationChannel(id);
        await refresh();
        showNotification(t('common.success'), 'success');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthRequired?.();
          return;
        }
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `删除渠道失败${message ? `: ${message}` : ''}`,
          'error'
        );
      }
    },
    [refresh, onAuthRequired, showNotification, t]
  );

  const testWebhook = useCallback(
    async (id: number): Promise<boolean> => {
      try {
        await testNotificationWebhook(id);
        showNotification(t('usage_stats.test_webhook_success'), 'success');
        return true;
      } catch (error) {
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `${t('usage_stats.test_webhook_failed')}${message ? `: ${message}` : ''}`,
          'error'
        );
        return false;
      }
    },
    [showNotification, t]
  );

  const createRule = useCallback(
    async (data: {
      name: string;
      channel_id: number;
      rule_type: string;
      config: { threshold?: number; window_minutes: number };
      enabled?: boolean;
      cooldown_minutes?: number;
    }) => {
      try {
        await createNotificationRule(data);
        await refresh();
        showNotification(t('common.success'), 'success');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthRequired?.();
          return;
        }
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `创建规则失败${message ? `: ${message}` : ''}`,
          'error'
        );
      }
    },
    [refresh, onAuthRequired, showNotification, t]
  );

  const updateRule = useCallback(
    async (
      id: number,
      data: {
        name?: string;
        channel_id?: number;
        rule_type?: string;
        config?: { threshold?: number; window_minutes: number };
        enabled?: boolean;
        cooldown_minutes?: number;
      }
    ) => {
      try {
        await updateNotificationRule(id, data);
        await refresh();
        showNotification(t('common.success'), 'success');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthRequired?.();
          return;
        }
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `更新规则失败${message ? `: ${message}` : ''}`,
          'error'
        );
      }
    },
    [refresh, onAuthRequired, showNotification, t]
  );

  const deleteRule = useCallback(
    async (id: number) => {
      try {
        await deleteNotificationRule(id);
        await refresh();
        showNotification(t('common.success'), 'success');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          onAuthRequired?.();
          return;
        }
        const message = error instanceof Error ? error.message : '';
        showNotification(
          `删除规则失败${message ? `: ${message}` : ''}`,
          'error'
        );
      }
    },
    [refresh, onAuthRequired, showNotification, t]
  );

  return {
    channels,
    rules,
    loading,
    refresh,
    createChannel,
    updateChannel,
    deleteChannel,
    testWebhook,
    createRule,
    updateRule,
    deleteRule,
  };
}
