import { useEffect, useState } from 'react';
import { useReducedMotion } from 'motion/react';

/**
 * Shared hook for auto-advancing product/narrative tour steps with
 * reduced-motion safety and manual play/pause controls.
 */
export function useTourAutoplay(stepCount: number, stepDuration = 6000) {
  const reduceMotion = useReducedMotion();
  const [activeStep, setActiveStep] = useState(0);
  // Keep the server and first client paint identical. Tours start paused and
  // retain explicit play/pause controls, including under reduced motion.
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    if (reduceMotion || !isPlaying) return;
    const interval = setInterval(() => {
      setActiveStep((prev) => (prev + 1) % stepCount);
    }, stepDuration);
    return () => clearInterval(interval);
  }, [reduceMotion, isPlaying, stepCount, stepDuration]);

  const selectStep = (index: number) => {
    setActiveStep(index);
    setIsPlaying(false);
  };

  const togglePlay = () => {
    setIsPlaying((prev) => !prev);
  };

  return {
    activeStep,
    setActiveStep,
    isPlaying: !reduceMotion && isPlaying,
    setIsPlaying,
    selectStep,
    togglePlay,
  };
}
