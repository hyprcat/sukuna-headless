/**
 * Run status icon/tone mappings shared across runs pages and dashboard.
 */
import circleCheck from 'lucide-static/icons/circle-check.svg?raw';
import circleAlert from 'lucide-static/icons/circle-alert.svg?raw';
import circleX from 'lucide-static/icons/circle-x.svg?raw';
import loader from 'lucide-static/icons/loader.svg?raw';
import clock from 'lucide-static/icons/clock.svg?raw';

export const statusIcon: Record<string, string> = {
  FINISHED: circleCheck,
  RUNNING: loader,
  FAILED: circleAlert,
  CANCELLED: circleX,
  QUEUED: clock,
};

export const statusTone: Record<string, string> = {
  FINISHED: 'text-ok',
  RUNNING: 'text-fg-2',
  FAILED: 'text-err',
  CANCELLED: 'text-fg-3',
  QUEUED: 'text-fg-3',
};

export { circleCheck };
