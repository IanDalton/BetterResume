import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Home } from './pages/Home';
import { Donate } from './pages/Donate';
import { ThankYou } from './pages/ThankYou';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/donate" element={<Donate />} />
        <Route path="/donate-checkout" element={<Donate />} />
        <Route path="/thank-you" element={<ThankYou />} />
        <Route path="/donate-success" element={<ThankYou />} />
      </Routes>
    </BrowserRouter>
  );
}
