import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'
import App from './App.jsx'
import { CompareProvider } from './hooks/useCompare.jsx'
import './styles/index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <HelmetProvider>
      <BrowserRouter>
        <CompareProvider>
          <App />
        </CompareProvider>
      </BrowserRouter>
    </HelmetProvider>
  </React.StrictMode>,
)
