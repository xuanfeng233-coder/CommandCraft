import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'cn.commandcraft.app',
  appName: 'CommandCraft',
  webDir: 'dist',
  server: {
    // Allow loading external LLM APIs
    allowNavigation: ['*'],
  },
  android: {
    // Allow mixed content (HTTP + HTTPS) for API calls
    allowMixedContent: true,
  },
};

export default config;
