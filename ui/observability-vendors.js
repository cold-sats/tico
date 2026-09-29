import {PostHog} from 'posthog-js/dist/module.no-external';
import * as Sentry from '@sentry/browser';

export function connect(config, filters) {
  let analytics = null, errors = false, active = true, errorClient = null;
  if (config.posthog_key && ['https://us.i.posthog.com', 'https://eu.i.posthog.com'].includes(config.posthog_host)) {
    try {
      analytics = new PostHog();
      // Pinned PostHog 1.430.3: retries bypass before_send. Fence actual dispatch
      // AND its callback, so failures arriving after reset cannot re-enqueue.
      const send = analytics._send_request.bind(analytics);
      analytics._send_request = options => {
        if (!active) return;
        return send({...options, callback: response => {
          if (active) options.callback?.(response);
        }});
      };
      analytics.init(config.posthog_key, {
        api_host: config.posthog_host, disable_compression:true, request_batching:false, persistence: 'memory', disable_persistence: true,
        bootstrap: {distinctID: config.distinct_id, isIdentifiedID: true},
        autocapture: false, capture_pageview: false, capture_pageleave: false,
        capture_dead_clicks: false, rageclick: false, capture_heatmaps: false,
        capture_performance: false, capture_exceptions: false, enable_recording_console_log: false,
        disable_session_recording: true, disable_surveys: true, disable_external_dependency_loading: true,
        advanced_disable_flags: true, advanced_disable_feature_flags: true,
        person_profiles: 'identified_only', ip: false, save_referrer: false, save_campaign_params: false,
        before_send: filters.posthog,
      });
    } catch (_) { analytics = null; }
  }
  if (config.sentry_dsn) {
    try {
      Sentry.init({dsn:config.sentry_dsn, environment:config.environment, release:config.release || undefined,
        sendDefaultPii:false, defaultIntegrations:false,
        integrations:[Sentry.globalHandlersIntegration()], beforeSend:filters.sentry,
        maxBreadcrumbs:0, autoSessionTracking:false, sendClientReports:false,
        tracesSampleRate:0, replaysSessionSampleRate:0, replaysOnErrorSampleRate:0});
      errorClient = Sentry.getClient();
      errors = true;
    } catch (_) { errors = false; }
  }
  return {
    identify(id) { try { analytics?.identify(id); } catch (_) {} try { if (errors) Sentry.setUser({id}); } catch (_) {} },
    capture(name, properties) { try { analytics?.capture(name, properties); } catch (_) {} },
    reset() {
      active = false;
      // Discard, never unload/flush: unload uses sendBeacon for queued events.
      const retry = analytics?._retryQueue;
      if (retry) {
        clearTimeout(retry._poller);
        retry._poller = undefined; retry._isPolling = false; retry._queue = [];
        window.removeEventListener('online', retry._onlineListener);
        window.removeEventListener('offline', retry._offlineListener);
      }
      try { analytics?.reset(true); } catch (_) {}
      analytics = null;
      try { if (errors) { Sentry.setUser(null); errorClient.getOptions().enabled = false; } } catch (_) {}
      errors = false;
    },
  };
}
