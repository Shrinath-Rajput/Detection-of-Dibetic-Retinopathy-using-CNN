// Enhanced animations and interactions for premium UI

document.addEventListener('DOMContentLoaded', function() {
    // Smooth scroll behavior
    document.documentElement.style.scrollBehavior = 'smooth';

    // Mobile menu toggle
    const menuToggle = document.getElementById('menuToggle');
    const navLinks = document.getElementById('navLinks');

    if (menuToggle && navLinks) {
        menuToggle.addEventListener('click', () => {
            navLinks.classList.toggle('active');
        });

        // Close menu when a link is clicked
        navLinks.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', () => {
                navLinks.classList.remove('active');
            });
        });
    }

    // Intersection Observer for fade-in animations
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };

    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);

    // Observe all animate elements
    document.querySelectorAll('.animate').forEach(el => {
        observer.observe(el);
    });

    // Add glow effect on button hover
    const buttons = document.querySelectorAll('button, .btn');
    buttons.forEach(btn => {
        btn.addEventListener('mouseenter', function(e) {
            const rect = this.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            const glow = document.createElement('div');
            glow.style.position = 'absolute';
            glow.style.width = '20px';
            glow.style.height = '20px';
            glow.style.background = 'radial-gradient(circle, rgba(255,255,255,0.5) 0%, transparent 70%)';
            glow.style.borderRadius = '50%';
            glow.style.left = x + 'px';
            glow.style.top = y + 'px';
            glow.style.pointerEvents = 'none';
            glow.style.animation = 'buttonGlow 0.6s ease-out forwards';

            this.style.position = 'relative';
            this.appendChild(glow);

            setTimeout(() => glow.remove(), 600);
        });
    });

    // Add card hover effect with parallax
    const cards = document.querySelectorAll('.card, .stat');
    cards.forEach(card => {
        card.addEventListener('mousemove', function(e) {
            const rect = this.getBoundingClientRect();
            const x = (e.clientX - rect.left) / rect.width;
            const y = (e.clientY - rect.top) / rect.height;

            const rotateX = (y - 0.5) * 5;
            const rotateY = (x - 0.5) * 5;

            this.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.02)`;
        });

        card.addEventListener('mouseleave', function() {
            this.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) scale(1)';
        });
    });

    // Add ripple effect to clickable elements
    const clickableElements = document.querySelectorAll('button, .btn, a');
    clickableElements.forEach(el => {
        el.addEventListener('click', function(e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            const size = Math.max(rect.width, rect.height);
            const x = e.clientX - rect.left - size / 2;
            const y = e.clientY - rect.top - size / 2;

            ripple.style.width = ripple.style.height = size + 'px';
            ripple.style.left = x + 'px';
            ripple.style.top = y + 'px';
            ripple.className = 'ripple';
            ripple.style.position = 'absolute';
            ripple.style.borderRadius = '50%';
            ripple.style.background = 'radial-gradient(circle, rgba(255,255,255,0.6), transparent)';
            ripple.style.transform = 'scale(0)';
            ripple.style.animation = 'rippleEffect 0.6s ease-out forwards';
            ripple.style.pointerEvents = 'none';

            this.style.position = 'relative';
            this.style.overflow = 'hidden';
            this.appendChild(ripple);

            setTimeout(() => ripple.remove(), 600);
        });
    });

    // Smooth page transition
    window.addEventListener('load', function() {
        document.body.style.opacity = '1';
        document.body.style.animation = 'fadeInUp 0.8s ease-out';
    });

    // Add scroll animations to hero sections
    const heroSections = document.querySelectorAll('.hero, .hero-dr');
    heroSections.forEach(hero => {
        window.addEventListener('scroll', () => {
            const scrollY = window.scrollY;
            const elementTop = hero.offsetTop;
            const elementHeight = hero.offsetHeight;

            if (scrollY > elementTop - window.innerHeight) {
                const scrollPercent = (scrollY - (elementTop - window.innerHeight)) / (elementHeight + window.innerHeight);
                hero.style.transform = `translateY(${scrollPercent * 20}px) scale(${1 - scrollPercent * 0.02})`;
            }
        });
    });

    // Animate counters if they exist
    const stats = document.querySelectorAll('.stat h3');
    let hasBeenViewed = false;

    const statsObserver = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting && !hasBeenViewed) {
                hasBeenViewed = true;
                animateCounters();
            }
        });
    }, { threshold: 0.5 });

    if (stats.length > 0) {
        stats.forEach(stat => statsObserver.observe(stat));
    }

    function animateCounters() {
        stats.forEach(stat => {
            const text = stat.textContent;
            if (text.includes('+') || text.includes('%') || text.match(/\d+/)) {
                stat.style.animation = 'bounceIn 0.8s ease-out';
            }
        });
    }

    // Add form validation with visual feedback
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const inputs = this.querySelectorAll('input, select');
            let isValid = true;

            inputs.forEach(input => {
                if (!input.value && input.hasAttribute('required')) {
                    isValid = false;
                    input.style.borderColor = '#FF6B6B';
                    input.style.animation = 'shake 0.3s ease-in-out';
                } else {
                    input.style.borderColor = '#00D9FF';
                }
            });

            if (!isValid) {
                e.preventDefault();
            }
        });
    });

    // Shake animation for invalid inputs
    const style = document.createElement('style');
    style.textContent = `
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            10%, 30%, 50%, 70%, 90% { transform: translateX(-5px); }
            20%, 40%, 60%, 80% { transform: translateX(5px); }
        }
        @keyframes buttonGlow {
            0% {
                opacity: 1;
                transform: scale(1);
            }
            100% {
                opacity: 0;
                transform: scale(2);
            }
        }
        @keyframes rippleEffect {
            0% {
                transform: scale(0);
                opacity: 1;
            }
            100% {
                transform: scale(4);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);

    // Add loading state for buttons during submission
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            const submitBtn = this.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.style.opacity = '0.7';
                submitBtn.textContent = '⏳ Processing...';
            }
        });
    });

    // Parallax background effect
    const parallaxElements = document.querySelectorAll('[class*="::before"], [class*="::after"]');
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        document.body.style.backgroundPosition = `0px ${scrollY * 0.5}px`;
    });
});

// Prevent multiple form submissions
let isSubmitting = false;
document.addEventListener('submit', function(e) {
    if (isSubmitting) {
        e.preventDefault();
        return;
    }
    isSubmitting = true;
    setTimeout(() => {
        isSubmitting = false;
    }, 3000);
});
