#!/usr/bin/env python
# -*- coding: utf-8 -*-
from math import sqrt
import numpy as np
import pygimli as pg

from pygimli.solver.leastsquares import lsqr as lssolver


class LSQRInversion(pg.Inversion):
    """LSQR solver based inversion"""

    def __init__(self, *args, **kwargs):
        """Init."""
        super().__init__(*args, **kwargs)
        self.G = None
        self.c = None
        self.my = 1.0

    def setParameterConstraints(self, G, c, my=1.0):
        """Set parameter constraints G*p=c."""
        self.G = G
        self.c = c
        self.my = my

    def oneStep(self):
        """One inversion step."""
        print("Running one inversion step!")
        model = self.model
        if len(self.response) != len(self.dataVals):
            self.setResponse(self.fop.response(model))

        self.fop.createJacobian(model)
        # self.checkTransFunctions()
        tD = self.dataTrans
        tM = self.modelTrans
        nData = len(self.dataVals)
        self.A = pg.BlockMatrix()  # to be filled with scaled J and C matrices
        # part 1: data part
        J = self.fop.jacobian()
        self.dScale = 1.0 / pg.log(self.errorVals+1.0)
        self.leftJ = tD.deriv(self.response) * self.dScale
#        self.leftJ = self.dScale / tD.deriv(self.response())
        self.rightJ = 1.0 / tM.deriv(model)
        self.JJ = pg.matrix.MultLeftRightMatrix(J, self.leftJ, self.rightJ)
#        self.A.addMatrix(self.JJ, 0, 0)
        self.mat1 = self.A.addMatrix(self.JJ)
        self.A.addMatrixEntry(self.mat1, 0, 0)
        # part 2: normal constraints
        # self.checkConstraints()
        self.C = self.fop.constraints()
        self.leftC = pg.Vector(self.C.rows(), 1.0)
        self.rightC = pg.Vector(self.C.cols(), 1.0)
        self.CC = pg.matrix.MultLeftRightMatrix(self.C,
                                                self.leftC, self.rightC)
        self.mat2 = self.A.addMatrix(self.CC)
        lam = self.lam
        self.A.addMatrixEntry(self.mat2, nData, 0, sqrt(lam))
        # % part 3: parameter constraints
        if self.G is not None:
            self.rightG = 1.0 / tM.deriv(model)
            self.GG = pg.matrix.MultRightMatrix(self.G, self.rightG)
            self.mat3 = self.A.addMatrix(self.GG)
            nConst = self.C.rows()
            self.A.addMatrixEntry(self.mat3, nData+nConst, 0, sqrt(self.my))

        self.A.recalcMatrixSize()
        # right-hand side vector
        deltaD = (tD.fwd(self.dataVals)-tD.fwd(self.response)) * self.dScale
        deltaC = -(self.CC * tM.fwd(model) * sqrt(lam))
        deltaC *= 1.0 - self.inv.localRegularization()  # oper. on DeltaM only
        rhs = pg.cat(deltaD, deltaC)
        if self.G is not None:
            deltaG = (self.c - self.G * model) * sqrt(self.my)
            rhs = pg.cat(pg.cat(deltaD, deltaC), deltaG)

        dM = lssolver(self.A, rhs, verbose=True)
        tau, responseLS = self.lineSearchInter(dM)
        if tau < 0.1:  # did not work out
            tau = self.lineSearchQuad(dM, responseLS)
        if tau > 0.9:  # save time and take 1
            tau = 1.0
        elif tau < 0.1:  # still not working
            tau = 0.1  # tra a small value

        self.model = tM.update(self.model, dM*tau)
        if tau == 1.0:
            self.inv.setResponse(responseLS)
        else:  # compute new response
            self.inv.setResponse(self.fop.response(self.model))

        # self.inv.setLambda(self.lam * self.inv.lambdaFactor())
        self.inv.setModel(self.model)
        return True

    def lineSearchInter(self, dM, nTau=100):
        """Optimizes line search parameter by linear respones interpolation."""
        tD = self.dataTrans
        tM = self.modelTrans
        model = self.model
        response = self.response
        modelLS = tM.update(model, dM)
        responseLS = self.fop.response(modelLS)
        taus = np.linspace(0.0, 1.0, nTau)
        phi = np.ones_like(taus) * self.phi()
        phi[-1] = self.phi(modelLS, responseLS)
        t0 = tD.fwd(response)
        t1 = tD.fwd(responseLS)
        for i in range(1, len(taus)-1):
            tau = taus[i]
            modelI = tM.update(model, dM*tau)
            responseI = tD.inv(t1*tau+t0*(1.0-tau))
            phi[i] = self.phi(modelI, responseI)

        pg.plt.plot(phi)
        return taus[np.argmin(phi)], responseLS

    def lineSearchQuad(self, dM, responseLS):
        """Optimize line search by fitting parabola by Phi(tau) curve."""
        return 0.1


if __name__ == '__main__':
    nlay = 4  # number of layers
    lam = 200.  # (initial) regularization parameter
    errPerc = 3.  # relative error of 3 percent
    ab2 = np.logspace(-1, 2, 50)  # AB/2 distance (current electrodes)
    mn2 = ab2 / 3.  # MN/2 distance (potential electrodes)
    # f = pg.core.DC1dModelling(nlay, ab2, mn2)
    f = pg.physics.ert.VESModelling(ab2=ab2, mn2=mn2, nLayers=nlay)
    synres = [100., 500., 20., 800.]  # synthetic resistivity
    synthk = [0.5, 3.5, 6.]  # synthetic thickness (nlay-th layer is infinite)
    rhoa = f(synthk+synres)
    rhoa = rhoa * (pg.randn(len(rhoa)) * errPerc / 100. + 1.)
    tLog = pg.trans.TransLog()

    inv = LSQRInversion(fop=f, verbose=True)
    # inv = pg.Inversion(fop=f)
    inv.dataTrans = tLog
    inv.modelTrans = tLog
    startModel = pg.cat(pg.Vector(nlay-1, 5), pg.Vector(nlay, pg.median(rhoa)))
    inv.inv.setMarquardtScheme()
    G = pg.Matrix(rows=1, cols=len(startModel))
    for i in range(3):
        G.setVal(0, i, 1)

    c = pg.Vector(1, pg.sum(synthk))
    inv.setParameterConstraints(G, c, 100)
    model = inv.run(rhoa, pg.Vector(len(rhoa), errPerc/100), lam=1000,
                    startModel=startModel)
    print(model)
    print(inv.chi2(), inv.relrms(), pg.sum(inv.model[:nlay-1]))
    # %%
    fig, ax = plt.subplots()
    ax.loglog(rhoa, ab2, "x")
    ax.loglog(inv.response, ab2, "-")
    # %%
    fig, ax = pg.plt.subplots()
    pg.viewer.mpl.drawModel1D(ax, model=model, plot="semilogx")
    pg.viewer.mpl.drawModel1D(ax, synthk, synres)
