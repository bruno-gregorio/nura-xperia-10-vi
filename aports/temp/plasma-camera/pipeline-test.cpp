// SPDX-License-Identifier: GPL-2.0-or-later
// On-device integration test: preview -> full-resolution photo -> preview,
// with the same Worker, threads and image ownership used by the application.
#include "plasmacamera/worker.h"
#include <QCoreApplication>
#include <QTimer>
#include <QThread>
#include <QDebug>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    if (argc != 2) {
        qCritical() << "Usage: plasma-camera-pipeline-test CAMERA_ID";
        return 2;
    }
    libcamera::CameraManager manager;
    if (manager.start()) return 2;
    auto camera = manager.get(argv[1]);
    if (!camera || camera->acquire()) return 2;
    auto full = camera->generateConfiguration({libcamera::StreamRole::StillCapture});
    if (!full) return 2;
    const QSize expected(full->at(0).size.width, full->at(0).size.height);
    full.reset();
    QThread thread;
    Worker *worker = new Worker;
    worker->moveToThread(&thread);
    int frames = 0, shots = 0;
    bool stopping = false;
    QImage retained;
    QByteArray retainedPixels;
    auto fail = [&](const QString &reason) { qCritical() << reason; app.exit(1); };
    QObject::connect(&thread, &QThread::started, worker, &Worker::init);
    QObject::connect(&thread, &QThread::finished, worker, &QObject::deleteLater);
    QObject::connect(worker, &Worker::ready, &app, [&] {
        if (stopping) return;
        QMetaObject::invokeMethod(worker, [=] { worker->setCamera(camera); });
    });
    QObject::connect(worker, &Worker::errorOccurred, &app, fail);
    QObject::connect(worker, &Worker::stillCaptureFrames, &app, [&](const QQueue<QImage> &images) {
        if (images.isEmpty() || images.head().size() != expected) {
            fail(QStringLiteral("Still capture lost the full-resolution image"));
            return;
        }
        ++shots;
        qInfo() << "Full-resolution photo PASS" << expected << "shot" << shots;
    });
    QObject::connect(worker, &Worker::viewFinderFrame, &app, [&](const QImage &image) {
        worker->acknowledgePreview();
        if (image.isNull() || image.width() > 1280 || image.height() > 960) {
            fail(QStringLiteral("Unexpected preview size"));
            return;
        }
        ++frames;
        if (frames == 30) {
            retained = image;
            retainedPixels = QByteArray(reinterpret_cast<const char *>(image.constBits()), image.sizeInBytes());
        }
        if (frames == 110 && retainedPixels != QByteArray(reinterpret_cast<const char *>(retained.constBits()), retained.sizeInBytes())) {
            fail(QStringLiteral("Preview pixels changed after the camera buffer was recycled"));
            return;
        }
        if (frames == 120 || frames == 240)
            QMetaObject::invokeMethod(worker, &Worker::capture);
        if (frames == 360) {
            if (shots != 2) { fail(QStringLiteral("Photo transition did not complete twice")); return; }
            qInfo() << "Preview/capture/restart and retained-image ownership PASS" << frames << "frames";
            app.quit();
        }
    });
    QTimer::singleShot(90000, &app, [&] { fail(QStringLiteral("Pipeline test timed out")); });
    thread.start();
    const int result = app.exec();
    stopping = true;
    QMetaObject::invokeMethod(worker, &Worker::unsetCamera, Qt::BlockingQueuedConnection);
    thread.quit();
    thread.wait();
    camera.reset();
    manager.stop();
    return result;
}
