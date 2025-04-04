$(function () {
  const container = $('#main .container');
  const style = getComputedStyle(document.body);

  function inputHidden(name, value, cssClass) {
    return $(
      '<input class="' +
        (cssClass || '') +
        '" type="hidden" name="' +
        name +
        '" value="' +
        value +
        '">',
    );
  }

  function awardBadge(badgeLevel) {
    // Update and show badge tooltip
    container
      .find('.badge-tooltip')
      .show()
      .find('.badge-name')
      .html('Community Builder')
      .end()
      .find('.level')
      .html(badgeLevel);

    // Throw confetti!
    const end = Date.now() + 5 * 1000;

    const config = {
      disableForReducedMotion: true,
      colors: [
        style.getPropertyValue('--status-error'),
        style.getPropertyValue('--white-1'),
      ],
      particleCount: 2,
      spread: 55,
    };

    (function frame() {
      confetti({
        ...config,
        angle: 60,
        origin: { x: 0 },
      });
      confetti({
        ...config,
        angle: 120,
        origin: { x: 1 },
      });

      if (Date.now() < end) {
        requestAnimationFrame(frame);
      }
    })();
  }

  container.on('click', '#permissions-form .save', function (e) {
    e.preventDefault();
    const $form = $('#permissions-form');

    // Remove stale permissions items (bug 1416890)
    $('input.permissions-form-item').remove();

    // Before submitting the form, update translators and managers
    $.each(['translators', 'managers'], function (i, value) {
      const data = $form.find('.user.' + value + ' li');
      data.each(function () {
        const itemId = $(this).data('id');

        if ($(this).parents('.general').length > 0) {
          $form.append(
            inputHidden('general-' + value, itemId, 'permissions-form-item'),
          );
        } else {
          // We have to retrieve an index of parent project locale form
          const localeProjectIndex = $(this)
            .parents('.project-locale')
            .data('index');
          $form.append(
            inputHidden(
              'project-locale-' + localeProjectIndex + '-translators',
              itemId,
              'permissions-form-item',
            ),
          );
        }
      });
    });

    $.ajax({
      url: $('#permissions-form').prop('action'),
      type: $('#permissions-form').prop('method'),
      data: $('#permissions-form').serialize(),
      success: function (response) {
        Pontoon.endLoader('Permissions saved.');

        const badgeLevel = $(response).find('#community-builder-level').val();
        if (badgeLevel > 0) {
          awardBadge(badgeLevel);
        }
      },
      error: function () {
        Pontoon.endLoader('Oops, something went wrong.', 'error');
      },
    });
  });

  // Switch available users
  container.on('click', '.user.available label a', function (e) {
    e.preventDefault();

    $(this).addClass('active').siblings('a').removeClass('active');

    const available = $(this).parents('.user.available');
    available.find('li').show();

    if ($(this).is('.contributors')) {
      available.find('li:not(".contributor")').hide();
    }

    available.find('.search-wrapper input').trigger('input').focus();
  });

  // While in contributors tab, search contributors only
  // Has to be attached to body, like the input.search event in main.js
  $('body').on(
    'input.search',
    '.user.available .menu input[type=search]',
    function () {
      const available = $(this).parents('.user.available');

      if (available.find('label a.contributors').is('.active')) {
        available.find('li:not(".contributor")').hide();
      }
    },
  );

  // Focus project selector search field
  container.on('click', '#project-selector .selector', function () {
    $('#project-selector .search-wrapper input').focus();
  });

  // Add project
  container.on('click', '#project-selector .menu li', function () {
    const slug = $(this).data('slug'),
      $permsForm = $(".project-locale[data-slug='" + slug + "']");

    $('.project-locale:last').after($permsForm.removeClass('hidden'));

    $permsForm.append(
      inputHidden(
        'project-locale-' +
          $permsForm.data('index') +
          '-has_custom_translators',
        1,
      ),
    );

    // Update menu (must be above Copying Translators)
    $(this).addClass('hidden').removeClass('limited').removeAttr('style');
    if ($('#project-selector .menu li:not(".hidden")').length === 0) {
      $('#project-selector').addClass('hidden');
    }

    // Initialize Project Contributors (must be above Copying Translators)
    if ($permsForm.find('.user.available li').length === 0) {
      $('.permissions-groups.general .user li').each(function () {
        $(this)
          .clone()
          .appendTo(
            ".project-locale[data-slug='" + slug + "'] .user.available ul",
          );
      });
    }

    // Initialize Project Translators with Managers and Translators from the General section
    $('.permissions-groups.general .user:not(".available") li').each(
      function () {
        $permsForm
          .find('.user.available li[data-id="' + $(this).data('id') + '"]')
          .click();
      },
    );

    // Scroll to the right project locale
    $('html, body').animate(
      {
        scrollTop: $permsForm.offset().top,
      },
      500,
    );
  });

  // Remove project
  container.on('click', '.remove-project', function (e) {
    const $permsForm = $(this).parents('.project-locale');
    e.preventDefault();

    $('#project-selector').removeClass('hidden');
    $("#project-selector li[data-slug='" + $permsForm.data('slug') + "']")
      .removeClass('hidden')
      .addClass('limited');

    $permsForm.find('input[name$=has_custom_translators]').remove();

    $permsForm.addClass('hidden');
    $permsForm.find('.select.translators li').each(function () {
      $permsForm.find('.select.available ul').append($(this).remove());
    });
  });

  // Hide badge tooltip on click on the Continue button or outside of the tooltip
  $(document).on('click', function (e) {
    const tooltip = container.find('.badge-tooltip');

    // Tooltip not visible
    if (!tooltip.is(':visible')) {
      return;
    }

    // Click inside the tooltip
    if (tooltip.is(e.target) || tooltip.has(e.target).length) {
      // Click on the Continue button
      if (e.target.className === 'continue') {
        e.preventDefault();
      } else {
        return;
      }
    }

    tooltip.hide();
  });
});
