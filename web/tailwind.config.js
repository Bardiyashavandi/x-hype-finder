/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'media',
  theme: {
    extend: {
      colors: {
        // Dark-mode-first palette reused from this project's own README
        // Mermaid diagrams (specs/003-web-dashboard/plan.md §3) — genuine
        // brand consistency between docs and UI, not a fresh palette.
        surface: {
          DEFAULT: '#0b0f17', // page background — near-black slate
          raised: '#111827', // card surfaces, one step lighter
          border: '#1f2937',
        },
        // Deterministic-pipeline actions (topics, digests, filters) — the
        // README diagrams' `pipelineNode` blue.
        pipeline: {
          DEFAULT: '#2563eb',
          bg: 'rgba(37, 99, 235, 0.12)',
          border: 'rgba(37, 99, 235, 0.4)',
        },
        // AI-derived content (Verdict, Summarize, Draft Post) — the README
        // diagrams' `agentNode` pink.
        agent: {
          DEFAULT: '#db2777',
          bg: 'rgba(219, 39, 119, 0.12)',
          border: 'rgba(219, 39, 119, 0.4)',
        },
        status: {
          success: '#22c55e', // published / kept
          pending: '#f59e0b', // held / pending — matches the diagrams' gate-node amber
          error: '#ef4444', // failed / error
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
