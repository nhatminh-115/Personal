import type { Metadata } from 'next';
import './globals.css';
import './kiosk.css';
import './theme.css';
import './intro.css';
import './polish.css';
export const metadata:Metadata={title:'Campus E · 3D Wayfinding Prototype',description:'Bản thử nghiệm chỉ đường 3D cho Cơ sở E'};
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>){return <html lang="vi"><body>{children}</body></html>}
