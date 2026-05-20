import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        muted: 'hsl(var(--muted))',
        'muted-foreground': 'hsl(var(--muted-foreground))',
        card: 'hsl(var(--card))',
        accent: 'hsl(var(--accent))',
        primary: 'hsl(var(--primary))',
        positive: 'hsl(var(--positive))',
        warning: 'hsl(var(--warning))',
        danger: 'hsl(var(--danger))'
      }
    }
  },
  plugins: []
} satisfies Config
