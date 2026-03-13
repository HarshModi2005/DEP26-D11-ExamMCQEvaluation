/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                // Primary Colors
                'primary': '#2563EB', // Professional blue (primary) - blue-600
                'primary-50': '#EFF6FF', // Light blue (50-level shade) - blue-50
                'primary-100': '#DBEAFE', // Light blue (100-level shade) - blue-100
                'primary-500': '#3B82F6', // Medium blue (500-level shade) - blue-500
                'primary-600': '#2563EB', // Primary blue (600-level shade) - blue-600
                'primary-700': '#1D4ED8', // Dark blue (700-level shade) - blue-700
                'primary-900': '#1E3A8A', // Very dark blue (900-level shade) - blue-900

                // Secondary Colors
                'secondary': '#64748B', // Sophisticated slate (secondary) - slate-500
                'secondary-50': '#F8FAFC', // Light slate (50-level shade) - slate-50
                'secondary-100': '#F1F5F9', // Light slate (100-level shade) - slate-100
                'secondary-200': '#E2E8F0', // Light slate (200-level shade) - slate-200
                'secondary-300': '#CBD5E1', // Light slate (300-level shade) - slate-300
                'secondary-400': '#94A3B8', // Medium slate (400-level shade) - slate-400
                'secondary-500': '#64748B', // Secondary slate (500-level shade) - slate-500
                'secondary-600': '#475569', // Dark slate (600-level shade) - slate-600
                'secondary-700': '#334155', // Dark slate (700-level shade) - slate-700
                'secondary-800': '#1E293B', // Very dark slate (800-level shade) - slate-800
                'secondary-900': '#0F172A', // Near black slate (900-level shade) - slate-900

                // Accent Colors
                'accent': '#059669', // Success-oriented emerald (accent) - emerald-600
                'accent-50': '#ECFDF5', // Light emerald (50-level shade) - emerald-50
                'accent-100': '#D1FAE5', // Light emerald (100-level shade) - emerald-100
                'accent-500': '#10B981', // Medium emerald (500-level shade) - emerald-500
                'accent-600': '#059669', // Accent emerald (600-level shade) - emerald-600
                'accent-700': '#047857', // Dark emerald (700-level shade) - emerald-700

                // Background Colors
                'background': '#FAFAFA', // Warm off-white background - gray-50
                'surface': '#FFFFFF', // Pure white surface - white

                // Text Colors
                'text-primary': '#0F172A', // Near-black primary text - slate-900
                'text-secondary': '#475569', // Medium gray secondary text - slate-600

                // Status Colors
                'success': '#10B981', // Clear positive feedback - emerald-500
                'success-50': '#ECFDF5', // Light success (50-level shade) - emerald-50
                'success-100': '#D1FAE5', // Light success (100-level shade) - emerald-100
                'success-600': '#059669', // Dark success (600-level shade) - emerald-600

                'warning': '#F59E0B', // Attention-grabbing amber - amber-500
                'warning-50': '#FFFBEB', // Light warning (50-level shade) - amber-50
                'warning-100': '#FEF3C7', // Light warning (100-level shade) - amber-100
                'warning-600': '#D97706', // Dark warning (600-level shade) - amber-600

                'error': '#EF4444', // Decisive red error - red-500
                'error-50': '#FEF2F2', // Light error (50-level shade) - red-50
                'error-100': '#FEE2E2', // Light error (100-level shade) - red-100
                'error-600': '#DC2626', // Dark error (600-level shade) - red-600

                // Border Colors
                'border': '#E2E8F0', // Minimal border color - slate-200
                'border-light': '#F1F5F9', // Light border color - slate-100
            },
            fontFamily: {
                'heading': ['Inter', 'sans-serif'], // Modern geometric sans-serif for headings
                'body': ['Inter', 'sans-serif'], // Consistent with headings for body text
                'caption': ['Inter', 'sans-serif'], // Unified font family for captions
                'mono': ['JetBrains Mono', 'monospace'], // Monospace for data and code
            },
            fontSize: {
                'xs': ['0.75rem', { lineHeight: '1rem' }],
                'sm': ['0.875rem', { lineHeight: '1.25rem' }],
                'base': ['1rem', { lineHeight: '1.5rem' }],
                'lg': ['1.125rem', { lineHeight: '1.75rem' }],
                'xl': ['1.25rem', { lineHeight: '1.75rem' }],
                '2xl': ['1.5rem', { lineHeight: '2rem' }],
                '3xl': ['1.875rem', { lineHeight: '2.25rem' }],
                '4xl': ['2.25rem', { lineHeight: '2.5rem' }],
            },
            boxShadow: {
                'sm': '0 1px 3px rgba(0, 0, 0, 0.1)',
                'md': '0 4px 6px rgba(0, 0, 0, 0.1)',
                'lg': '0 10px 25px rgba(0, 0, 0, 0.15)',
                'xl': '0 20px 40px rgba(0, 0, 0, 0.2)',
            },
            borderRadius: {
                'sm': '0.25rem',
                'md': '0.375rem',
                'lg': '0.5rem',
                'xl': '0.75rem',
            },
            spacing: {
                '18': '4.5rem',
                '88': '22rem',
                '240': '60rem',
            },
            zIndex: {
                '90': '90',
                '100': '100',
                '150': '150',
                '200': '200',
                '300': '300',
            },
            transitionDuration: {
                '150': '150ms',
                '200': '200ms',
                '300': '300ms',
            },
            transitionTimingFunction: {
                'ease-out': 'cubic-bezier(0, 0, 0.2, 1)',
                'ease-in-out': 'cubic-bezier(0.4, 0, 0.2, 1)',
            },
        },
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('tailwindcss-animate'),
    ],
}