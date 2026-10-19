import '@fontsource/be-vietnam-pro/400.css';import '@fontsource/be-vietnam-pro/500.css';import '@fontsource/be-vietnam-pro/600.css';import '@fontsource/be-vietnam-pro/700.css';
import React from 'react';
import { createRoot } from 'react-dom/client';
import CampusEMap from '../components/CampusEMap';
import '../app/globals.css';
import '../app/kiosk.css';
import '../app/theme.css';
import '../app/intro.css';
import '../app/polish.css';

createRoot(document.getElementById('root')!).render(
  <React.StrictMode><CampusEMap /></React.StrictMode>,
);
