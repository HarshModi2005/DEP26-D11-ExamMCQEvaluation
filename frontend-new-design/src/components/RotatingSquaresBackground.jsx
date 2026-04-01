import React, { useMemo } from 'react';

const MAX_SQUARES = 12; // Reduced: exponential growth covers the viewport much faster
const DARK_BLUE = '#4A6984';
const LIGHT_BLUE = '#7995AF';

const RotatingSquaresBackground = () => {
    const squares = useMemo(() => {
        const items = [];

        // Render from largest (bottom layer, i=12) to smallest (top layer, i=1)
        for (let i = MAX_SQUARES; i >= 1; i--) {
            // FIX: Exponential sizing ensures inner squares never clip through outer squares.
            // Each outer square's side must exceed the inner square's diagonal (side × √2).
            // Factor 1.5 > √2 ≈ 1.414, so clipping is geometrically impossible.
            const size = 10 * Math.pow(1.5, i);

            const color = i % 2 === 0 ? DARK_BLUE : LIGHT_BLUE;

            // Speed logic: smaller 'i' (closer to center) = shorter duration = faster spin
            const duration = (i * 1.5) + 2;

            items.push(
                <div
                    key={i}
                    className="rotating-square"
                    style={{
                        width: `${size}vmin`,
                        height: `${size}vmin`,
                        backgroundColor: color,
                        animationDuration: `${duration}s`,
                    }}
                />
            );
        }
        return items;
    }, []);

    return (
        <div
            className="rotating-squares-container"
            aria-hidden="true"
        >
            {squares}
        </div>
    );
};

export default RotatingSquaresBackground;
