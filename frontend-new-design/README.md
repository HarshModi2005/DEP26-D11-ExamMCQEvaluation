# Answer Key Evaluation DEP - Frontend

This is the modern React-based frontend for the Answer Key Evaluation DEP system. It provides an intuitive interface for Faculty, TAs, and Admins to manage courses, process student answer sheets, track evaluations via a Kanban board, and manage results.

## 🚀 Features

- **Faculty Dashboard**: An intuitive overview for creating courses, tracking evaluations, and managing pending grading tasks.
- **Team Management**: Robust controls to assign and invite Teaching Assistants to manage evaluations.
- **Kanban Board**: Drag-and-drop task tracking for grading assignments.
- **Modern UI**: Built with React 18, Vite, and TailwindCSS for a lightning-fast, responsive user experience.
- **State Management**: Redux Toolkit for simplified and robust state management.
- **Data Visualization**: Integrated D3.js and Recharts for powerful evaluation analytics.

## 📋 Prerequisites

- Node.js (v18.x or higher recommended)
- npm or yarn

## 🛠️ Installation & Setup

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Environment Variables:**
   Create a `.env` or `.env.local` file in this directory with the necessary variables. For example, you might need Supabase configuration keys:
   ```env
   VITE_SUPABASE_URL=your_supabase_url
   VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
   ```
   *Check `.env.example` if available.*

3. **Start the development server:**
   ```bash
   npm start
   ```
   *The frontend application will start up, usually available on `http://localhost:5173`.*

> **⚠️ IMPORTANT:** You must start the backend server before the frontend. The frontend relies heavily on backend API endpoints for processing data and authentication.

## 📁 Project Structure

```
frontend-new-design/
├── public/             # Static assets
├── src/
│   ├── components/     # Reusable UI components
│   ├── pages/          # Page components (e.g., Faculty Dashboard, Auth)
│   ├── App.jsx         # Main application component
│   ├── Routes.jsx      # Application routes using React Router
│   └── index.jsx       # Application entry point
├── package.json        # Project dependencies and scripts
├── tailwind.config.js  # Tailwind CSS configuration
└── vite.config.mjs     # Vite configuration
```

## 📦 Deployment

Build the application for production:

```bash
npm run build
```
The optimized production build will be output to the `dist/` directory.

## 🎨 Styling

This project uses Tailwind CSS for styling. The configuration includes several powerful plugins:
- `@tailwindcss/forms` for form styling
- `@tailwindcss/typography` for text styling
- `@tailwindcss/aspect-ratio` for responsive elements
- Custom fluid typography and animation utilities

## 🙏 Acknowledgments

- Powered by React and Vite
- Styled with Tailwind CSS
