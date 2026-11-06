document.addEventListener('DOMContentLoaded', function () {
    const appShell = document.querySelector('.app-shell');
    const sidebarToggle = document.querySelector('.sidebar-toggle');
    const notifyButton = document.querySelector('.notify-button');

    if (appShell && sidebarToggle) {
        sidebarToggle.addEventListener('click', function () {
            appShell.classList.toggle('sidebar-collapsed');
            const collapsed = appShell.classList.contains('sidebar-collapsed');
            sidebarToggle.innerHTML = collapsed
                ? '<i class="fa-solid fa-arrow-left"></i>'
                : '<i class="fa-solid fa-bars"></i>';
        });
    }

    if (notifyButton) {
        notifyButton.addEventListener('click', function () {
            notifyButton.classList.toggle('pulse');
            notifyButton.setAttribute('title', 'لديك إشعارات جديدة');
        });
    }

    const flashAlerts = document.querySelectorAll('.alert');
    flashAlerts.forEach(function (alert, index) {
        setTimeout(function () {
            alert.style.opacity = '0';
            alert.style.transform = 'translateY(-4px)';
            alert.style.transition = 'all 0.25s ease';
        }, 3000 + index * 200);
    });

    const searchInputs = document.querySelectorAll('.sidebar-search input, .top-search-box input');
    searchInputs.forEach(function (input) {
        input.addEventListener('focus', function () {
            input.parentElement?.classList.add('search-focused');
        });

        input.addEventListener('blur', function () {
            input.parentElement?.classList.remove('search-focused');
        });
    });
});
