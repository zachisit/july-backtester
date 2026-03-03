# utils.py
import matplotlib.pyplot as plt
import warnings
import os
from typing import TYPE_CHECKING

from . import default_config as config

if TYPE_CHECKING:
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

def save_pdf_fig(fig: 'Figure | None', pdf_pages: 'PdfPages', page_num_str: str):
    """
    Applies final layout adjustments (optional), adds page number,
    saves figure to PDF, and CLOSES the figure afterwards.
    """
    if fig is None or not isinstance(fig, plt.Figure):
        print(f"Warning: Invalid figure object passed for saving PDF page '{page_num_str}'. Skipping save.")
        return

    try:
        # Ensure the correct figure is active if it still exists
        if plt.fignum_exists(fig.number):
            plt.figure(fig.number) # Activate the figure

            # Add page number - use figure coordinates
            fig.text(0.5, 0.01, page_num_str, ha='center', va='bottom', size=8, color='gray')

            # Save the figure to the PDF object
            # bbox_inches='tight' helps prevent labels getting cut off
            pdf_pages.savefig(fig, bbox_inches='tight', pad_inches=0.1)

    except Exception as e:
        # Attempt to get title, provide default if not available
        fig_title = "Figure (No Title)"
        try:
            # Try accessing title through different attributes
            if hasattr(fig, '_suptitle') and fig._suptitle and hasattr(fig._suptitle, 'get_text'):
                fig_title = fig._suptitle.get_text() or fig_title
            elif fig.axes and hasattr(fig.axes[0], 'get_title') and fig.axes[0].get_title():
                 fig_title = fig.axes[0].get_title() or fig_title
        except Exception:
            pass # Ignore errors just trying to get the title for the warning

        print(f"Warning: Could not save figure '{fig_title}' to PDF (Page '{page_num_str}'). Error: {e}")
        # We don't attempt fallback save here as it might hide underlying issues.
        # The primary savefig failed.
    finally:
        # Ensure the figure is closed to release memory, only if it exists
        # This is crucial as figures are kept open until saved to PDF.
        if plt.fignum_exists(fig.number):
            plt.close(fig)

def save_figure_as_image(fig: 'Figure | None', output_path: str):
    """
    Saves a matplotlib figure as an image file (e.g., PNG) to the specified path.
    Does NOT close the figure. Ensures the output directory exists.
    """
    if fig is None or not isinstance(fig, plt.Figure):
        print(f"Warning: Invalid figure object passed for saving image to '{output_path}'. Skipping.")
        return False # Indicate failure

    try:
        # Ensure the output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir: # Only create if path includes a directory part
            os.makedirs(output_dir, exist_ok=True)

        # Ensure the correct figure is active
        if plt.fignum_exists(fig.number):
             plt.figure(fig.number) # Activate the figure

             # Save the figure as an image file
             # Use bbox_inches='tight' for better layout in the saved image
             fig.savefig(output_path, bbox_inches='tight', pad_inches=0.1)
             # Now this line will work because config is imported
             if config.VERBOSE_DEBUG: print(f"[DEBUG IMAGE SAVE] Saved plot image to: {output_path}")
             return True # Indicate success
        else:
             print(f"Warning: Figure {fig.number} no longer exists. Cannot save image to '{output_path}'.")
             return False # Indicate failure

    except Exception as e:
        fig_title = "Figure (Unknown)"
        try: # Try to get title for error message
             if hasattr(fig, '_suptitle') and fig._suptitle: fig_title = fig._suptitle.get_text() or fig_title
        except Exception: pass
        print(f"ERROR saving figure '{fig_title}' as image to '{output_path}': {e}")
        return False # Indicate failure