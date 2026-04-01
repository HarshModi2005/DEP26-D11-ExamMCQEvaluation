import React from 'react';
import RotatingSquaresBackground from './RotatingSquaresBackground';

const AppLayout = ({ children }) => {
    return (
        <>
            <RotatingSquaresBackground />
            <div className="app-content-window">
                {children}
            </div>
        </>
    );
};

export default AppLayout;
