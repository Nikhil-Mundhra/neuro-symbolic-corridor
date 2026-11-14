import React from 'react';

interface CorridorBrandMarkProps {
  size?: number;
  variant?: 'emblem' | 'lockup';
  theme?: 'auto' | 'dark' | 'light' | 'monochrome';
  className?: string;
  showBadge?: boolean;
}

const PIN_PATH = "M 764 0 L 722 0 L 670 9 L 635 21 L 593 43 L 563 65 L 529 99 L 505 132 L 488 164 L 485 174 L 486 180 L 492 188 L 496 190 L 506 190 L 510 188 L 516 181 L 535 144 L 559 113 L 590 84 L 625 61 L 650 49 L 688 37 L 718 32 L 757 31 L 784 34 L 814 41 L 846 53 L 879 71 L 903 89 L 933 119 L 955 149 L 973 184 L 985 220 L 992 270 L 991 306 L 982 360 L 965 417 L 944 469 L 914 529 L 885 579 L 848 635 L 806 691 L 768 735 L 745 757 L 742 757 L 718 734 L 679 688 L 671 684 L 664 684 L 658 687 L 653 694 L 652 702 L 655 709 L 693 754 L 726 785 L 743 792 L 752 790 L 766 781 L 791 757 L 820 724 L 879 646 L 933 560 L 969 490 L 996 424 L 1014 361 L 1023 300 L 1023 262 L 1020 235 L 1014 207 L 1006 182 L 996 158 L 981 131 L 950 90 L 934 74 L 907 52 L 884 37 L 863 26 L 817 9 L 789 3 Z M 731 168 L 711 172 L 688 182 L 672 193 L 657 208 L 646 224 L 637 244 L 632 267 L 632 292 L 636 312 L 647 337 L 657 351 L 673 367 L 686 376 L 711 387 L 731 391 L 756 391 L 779 386 L 799 377 L 815 366 L 830 351 L 841 335 L 852 308 L 855 291 L 855 268 L 852 251 L 841 224 L 830 208 L 815 193 L 799 182 L 772 171 L 756 168 Z M 738 199 L 762 201 L 774 205 L 794 217 L 806 229 L 813 239 L 820 254 L 824 275 L 823 292 L 820 305 L 813 320 L 806 330 L 794 342 L 781 351 L 766 357 L 751 360 L 736 360 L 721 357 L 706 351 L 693 342 L 680 329 L 671 315 L 666 302 L 663 286 L 663 273 L 666 257 L 672 242 L 681 229 L 701 211 L 718 203 Z";
const SHIP_PATH = "M 130 303 L 128 307 L 128 356 L 133 364 L 176 393 L 176 506 L 72 585 L 65 593 L 64 604 L 172 805 L 172 810 L 157 801 L 126 789 L 97 784 L 66 785 L 37 792 L 7 806 L 0 815 L 0 824 L 3 830 L 8 834 L 21 835 L 39 825 L 65 817 L 83 815 L 101 816 L 116 819 L 136 826 L 153 836 L 180 848 L 205 854 L 229 856 L 252 854 L 273 849 L 289 843 L 330 822 L 349 817 L 367 815 L 391 817 L 412 823 L 446 841 L 470 850 L 488 854 L 512 856 L 535 854 L 553 850 L 581 839 L 616 821 L 632 817 L 652 815 L 668 816 L 690 821 L 703 826 L 736 844 L 765 853 L 792 856 L 818 854 L 843 848 L 860 841 L 887 826 L 903 820 L 922 816 L 941 815 L 962 818 L 979 823 L 1002 835 L 1012 835 L 1020 830 L 1023 824 L 1023 816 L 1021 811 L 1016 806 L 986 792 L 968 787 L 947 784 L 925 784 L 897 789 L 870 799 L 833 818 L 804 824 L 785 824 L 763 820 L 740 811 L 705 793 L 684 787 L 663 784 L 642 784 L 617 788 L 589 798 L 561 813 L 560 811 L 665 616 L 671 604 L 671 596 L 669 591 L 663 585 L 560 508 L 559 393 L 599 366 L 605 360 L 607 355 L 607 308 L 605 303 L 600 298 L 595 296 L 527 295 L 527 228 L 525 223 L 520 218 L 516 216 L 383 215 L 383 164 L 381 159 L 376 154 L 371 152 L 363 152 L 354 159 L 352 164 L 352 214 L 350 216 L 219 216 L 212 220 L 208 227 L 207 296 L 140 296 L 135 298 Z M 100 605 L 196 531 L 234 504 L 253 495 L 348 465 L 352 466 L 352 740 L 355 746 L 363 751 L 375 750 L 379 747 L 383 739 L 384 465 L 467 490 L 501 504 L 635 605 L 528 805 L 524 822 L 520 824 L 502 824 L 480 820 L 461 813 L 442 802 L 419 792 L 401 787 L 380 784 L 359 784 L 330 789 L 310 796 L 274 815 L 260 820 L 238 824 L 218 824 L 211 822 L 208 809 L 201 792 Z M 159 329 L 161 327 L 574 327 L 576 329 L 576 342 L 533 371 L 528 379 L 526 483 L 512 474 L 492 465 L 371 427 L 360 428 L 243 465 L 207 482 L 207 380 L 205 375 L 199 369 L 159 342 Z M 239 249 L 241 247 L 494 247 L 496 249 L 496 294 L 494 296 L 239 295 Z";
const WAVE_PATH = "M 141 924 L 144 933 L 148 937 L 167 947 L 190 955 L 212 959 L 244 959 L 266 955 L 289 947 L 325 928 L 355 920 L 384 920 L 403 924 L 417 929 L 450 947 L 482 957 L 495 959 L 528 959 L 565 950 L 608 928 L 623 923 L 654 919 L 674 921 L 695 927 L 725 943 L 753 954 L 778 959 L 811 959 L 833 955 L 851 949 L 870 940 L 880 931 L 881 919 L 874 910 L 862 908 L 843 918 L 823 925 L 805 928 L 776 927 L 749 919 L 715 901 L 696 894 L 673 889 L 644 888 L 622 891 L 598 898 L 566 915 L 543 924 L 522 928 L 501 928 L 473 922 L 436 903 L 409 893 L 389 889 L 361 888 L 334 892 L 315 898 L 274 919 L 246 927 L 218 928 L 200 925 L 182 919 L 160 908 L 149 910 L 143 916 Z";

export const CorridorBrandMark: React.FC<CorridorBrandMarkProps> = ({
  size = 24,
  variant = 'emblem',
  theme = 'auto',
  className = '',
  showBadge = true,
}) => {
  const isDark = theme === 'dark' || theme === 'auto';
  const isMono = theme === 'monochrome';

  // Gulf Gold Colorway: Amber Gold Pin, Ink/Paper Vessel, Marine Emerald Waves
  const cPin = isMono ? 'currentColor' : 'var(--brand-amber)';
  const cShip = isMono ? 'currentColor' : isDark ? 'var(--ink-paper)' : 'var(--ink-obsidian)';
  const cWave = isMono ? 'currentColor' : 'var(--brand-accent)';

  const svgEmblem = (
    <svg
      viewBox="0 0 1024 960"
      width={size}
      height={Math.round(size * 0.9375)}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Gulf Corridor Maritime Brand Mark"
      style={{ flexShrink: 0 }}
    >
      {/* Map Location Pin (Gulf Gold) */}
      <path d={PIN_PATH} fill={cPin} fillRule="evenodd" />
      {/* Cargo Vessel (Crisp White) */}
      <path d={SHIP_PATH} fill={cShip} fillRule="evenodd" />
      {/* Ocean Waves (Marine Emerald) */}
      <path d={WAVE_PATH} fill={cWave} fillRule="evenodd" />
    </svg>
  );

  if (variant === 'lockup') {
    return (
      <div
        className={`corridor-brand-lockup ${className}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.65rem',
          textDecoration: 'none',
          color: 'inherit',
          userSelect: 'none',
        }}
      >
        {svgEmblem}
        <div className="corridor-brand-text">
          <span className="corridor-brand-kicker">Gulf Corridor</span>
          <div className="corridor-brand-title-row">
            <span className="corridor-brand-name">Dispatch Twin</span>
            {showBadge && <span className="corridor-brand-badge">Live</span>}
          </div>
        </div>
      </div>
    );
  }

  return svgEmblem;
};

export default CorridorBrandMark;
