import React from 'react';
import * as LucideIcons from 'lucide-react';

const AppIcon = ({ name, size = 24, color = "currentColor", className = "", ...props }) => {
    const IconComponent = LucideIcons[name];

    if (!IconComponent) {
        console.warn(`Icon "${name}" not found in lucide-react`);
        return <LucideIcons.HelpCircle size={size} color={color} className={className} {...props} />;
    }

    return <IconComponent size={size} color={color} className={className} {...props} />;
};

export default AppIcon;
