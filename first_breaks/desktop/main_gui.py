import sys
import time
import warnings
from pathlib import Path
from typing import Optional, Union

from PyQt5.QtCore import QSize, QThreadPool
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QWidget, QSizePolicy, QApplication, QMainWindow, QToolBar, QAction, QFileDialog, QLabel, \
    QDesktopWidget, QProgressBar, QHBoxLayout

from first_breaks.const import CKPT_HASH
from first_breaks.desktop.picking_widget import PickingWindow
from first_breaks.desktop.warn_widget import WarnBox
from first_breaks.desktop.graph import GraphWidget
from first_breaks.desktop.threads import InitNet, PickerQRunnable
from first_breaks.picker.picker import PickerONNX, Task
from first_breaks.sgy.reader import SGY
from first_breaks.utils.utils import calc_hash

warnings.filterwarnings("ignore")


class FileState:
    valid_file = 0
    file_not_exists = 1
    file_changed = 2

    @classmethod
    def get_file_state(cls, fname: Union[str, Path], fhash: str):
        if not Path(fname).is_file():
            return cls.file_not_exists
        else:
            return cls.valid_file if calc_hash(fname) == fhash else cls.file_changed


class ReadyToProcess:
    sgy_selected: bool = False
    model_loaded: bool = False

    def is_ready(self) -> bool:
        return (self.sgy_selected == self.model_loaded) is True


class MainWindow(QMainWindow):

    def __init__(self):
        super(MainWindow, self).__init__()

        if getattr(sys, 'frozen', False):
            self.main_folder = Path(sys._MEIPASS)
        else:
            self.main_folder = Path(__file__).parent

        # main window settings
        left = 100
        top = 100
        width = 700
        height = 700
        self.setGeometry(left, top, width, height)

        qt_rectangle = self.frameGeometry()
        center_point = QDesktopWidget().availableGeometry().center()
        qt_rectangle.moveCenter(center_point)
        self.move(qt_rectangle.topLeft())

        self.setWindowTitle('First breaks picking')

        # toolbar
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(30, 30))
        self.addToolBar(toolbar)

        # buttons on toolbar
        self.button_load_nn = QAction(QIcon(str(self.main_folder / "icons" / "nn.png")), "Load model", self)
        self.button_load_nn.triggered.connect(self.load_nn)
        self.button_load_nn.setEnabled(True)
        toolbar.addAction(self.button_load_nn)

        self.button_get_filename = QAction(QIcon(str(self.main_folder / "icons" / "sgy.png")), "Open SGY-file", self)
        self.button_get_filename.triggered.connect(self.get_filename)
        self.button_get_filename.setEnabled(True)
        toolbar.addAction(self.button_get_filename)

        toolbar.addSeparator()

        self.button_fb = QAction(QIcon(str(self.main_folder / "icons" / "picking.png")), "Neural network FB picking",
                                 self)
        self.button_fb.triggered.connect(self.calc_fb)
        self.button_fb.setEnabled(False)
        toolbar.addAction(self.button_fb)

        self.button_export = QAction(QIcon(str(self.main_folder / "icons" / "export.png")), "Export picks to file",
                                     self)
        # self.button_export.triggered.connect(self.export)
        self.button_export.setEnabled(False)
        toolbar.addAction(self.button_export)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        toolbar.addWidget(spacer)

        self.button_git = QAction(QIcon(str(self.main_folder / "icons" / "github.png")),
                                  "Open Github repo with project", self)
        # self.button_git.triggered.connect(self.open_github)
        toolbar.addAction(self.button_git)

        self.status = self.statusBar()
        self.status_progress = QProgressBar()
        self.status_progress.hide()

        self.status_message = QLabel()
        self.status_message.setText('Open SGY file or load model')

        status_widget = QWidget()
        status_layout = QHBoxLayout()
        status_widget.setLayout(status_layout)
        status_layout.addWidget(self.status_progress)
        status_layout.addWidget(self.status_message)

        self.status.addPermanentWidget(status_widget)

        # graph widget
        self.graph = GraphWidget(background='w')
        self.graph.hide()
        self.setCentralWidget(self.graph)

        # picking widget
        self.picking = PickingWindow()
        self.picking.hide()

        # placeholders
        self.sgy = None
        self.fn = None
        self.picks = None
        self.ready_to_process = ReadyToProcess()
        self.picker: Optional[PickerONNX] = None
        self.start_time = None
        self.end_time = None

        self.threadpool = QThreadPool()
        # self.threadpool.setMaxThreadCount(2)

        self.show()

    def _thread_init_net(self, weights: Union[str, Path]):
        worker = InitNet(weights)
        worker.signals.finished.connect(self.init_net)
        self.threadpool.start(worker)

    def init_net(self, picker: PickerONNX):
        self.picker = picker

    def calc_fb(self):
        self.button_fb.setEnabled(False)
        self.button_get_filename.setEnabled(False)
        task = Task(sgy=self.fn, traces_per_gather=2)
        worker = PickerQRunnable(self.picker, task)
        worker.signals.started.connect(self.start_fb)
        worker.signals.result.connect(self.result_fb)
        worker.signals.progress.connect(self.progress_fb)
        worker.signals.message.connect(self.message_fb)
        worker.signals.finished.connect(self.finish_fb)
        self.threadpool.start(worker)
        self.start_time = time.perf_counter()

    def start_fb(self):
        self.status_progress.show()

    def message_fb(self, message: str):
        self.status_message.setText(message)

    def finish_fb(self):
        self.status_progress.hide()
        self.button_fb.setEnabled(True)

    def progress_fb(self, value: int):
        self.status_progress.setValue(value)

    def result_fb(self, result: Task):
        self.end_time = time.perf_counter()
        print(self.end_time - self.start_time,
              (self.end_time - self.start_time) / result.num_batches,
              result.num_batches)
        if result.success:
            self.graph.plot_picks(result)
        else:
            window_error = WarnBox(self, title='InternalError', message=result.error_message)
            window_error.exec_()

        self.button_get_filename.setEnabled(True)
        self.button_fb.setEnabled(True)

    def show_sgy(self):
        try:
            self.sgy = SGY(self.fn)
            self.graph.clear()
            self.graph.plotseis_sgy(self.fn, negative_patch=True)
            self.graph.show()

        except Exception as e:
            window_err = WarnBox(self,
                                 title=e.__class__.__name__,
                                 message=str(e))
            window_err.exec_()
        finally:
            self.button_get_filename.setEnabled(True)

    def unlock_pickng_if_ready(self):
        if self.ready_to_process.is_ready():
            self.button_fb.setEnabled(True)
            self.status_message.setText('Click on picking to start processing')

    def load_nn(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getOpenFileName(self, "Select file with NN weights", options=options)

        if filename:
            if FileState.get_file_state(filename, CKPT_HASH) == FileState.valid_file:
                self._thread_init_net(weights=filename)

                self.button_load_nn.setEnabled(False)
                self.ready_to_process.model_loaded = True

                status_message = 'Model loaded successfully'
                if not self.ready_to_process.sgy_selected:
                    status_message += ". Open SGY file to start picking"
                self.status_message.setText(status_message)

                self.unlock_pickng_if_ready()
            else:
                window_err = WarnBox(self,
                                     title="Model loading error",
                                     message="The file cannot be used as model weights. "
                                             "Download the file according to the manual and select it.")
                window_err.exec_()

    def get_filename(self):
        options = QFileDialog.Options()
        filename, _ = QFileDialog.getOpenFileName(self, "Open SGY-file", "",
                                                  "SGY-file (*.sgy)", options=options)
        if filename:
            self.fn = Path(filename)
            self.picks = None
            self.show_sgy()

            self.ready_to_process.sgy_selected = True

            if not self.ready_to_process.model_loaded:
                status_message = "Load model to start picking"
                self.status_message.setText(status_message)

            self.unlock_pickng_if_ready()


if __name__ == '__main__':
    app = QApplication([])
    window = MainWindow()
    app.exec_()
