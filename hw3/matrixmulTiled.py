#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import division

""" 
This code is adapted from the example found at : https://wiki.tiker.net/PyCuda/Examples/MatrixmulTiled

The program takes 2 square matrices as numpy arrays, and multiplies two square matrices together using multiple blocks and shared memory. 
Each thread block is assigned a "tile" of the resulting matrix and is responsible
for generating the elements in that tile.  Each thread in a block computes one element 
of the tile.

We also compute the difference in the result when the calculations are done on the CPU vs the GPU using the gpuarray module of pycuda
"""

import numpy as np
from numpy import linalg as la
from pycuda import driver, compiler, gpuarray, tools

# -- initialize the device
import pycuda.autoinit

kernel_code_template = """
__global__ void MatrixMulKernel(float *A, float *B, float *C)
{

  const uint wA = %(MATRIX_SIZE)s;
  const uint wB = %(MATRIX_SIZE)s;  
  
  // Block index
  const uint bx = blockIdx.x;
  const uint by = blockIdx.y;

  // Thread index
  const uint tx = threadIdx.x;
  const uint ty = threadIdx.y;

  // Index of the first sub-matrix of A processed by the block
  const uint aBegin = wA * %(BLOCK_SIZE)s * by;
  // Index of the last sub-matrix of A processed by the block
  const uint aEnd = aBegin + wA - 1;
  // Step size used to iterate through the sub-matrices of A
  const uint aStep = %(BLOCK_SIZE)s;

  // Index of the first sub-matrix of B processed by the block
  const uint bBegin = %(BLOCK_SIZE)s * bx;
  // Step size used to iterate through the sub-matrices of B
  const uint bStep = %(BLOCK_SIZE)s * wB;

  // The element of the block sub-matrix that is computed
  // by the thread
  float Csub = 0;
  // Loop over all the sub-matrices of A and B required to
  // compute the block sub-matrix
  for (int a = aBegin, b = bBegin;
       a <= aEnd;
       a += aStep, b += bStep) 
    {
      // Shared memory for the sub-matrix of A
      __shared__ float As[%(BLOCK_SIZE)s][%(BLOCK_SIZE)s];
      // Shared memory for the sub-matrix of B
      __shared__ float Bs[%(BLOCK_SIZE)s][%(BLOCK_SIZE)s];

      // Load the matrices from global memory to shared memory
      // each thread loads one element of each matrix
      As[ty][tx] = A[a + wA * ty + tx];
      Bs[ty][tx] = B[b + wB * ty + tx];
      // Synchronize to make sure the matrices are loaded
      __syncthreads();

      // Multiply the two matrices together;
      // each thread computes one element
      // of the block sub-matrix
      for (int k = 0; k < %(BLOCK_SIZE)s; ++k)
        Csub += As[ty][k] * Bs[k][tx];

      // Synchronize to make sure that the preceding
      // computation is done before loading two new
      // sub-matrices of A and B in the next iteration
      __syncthreads();
    }

  // Write the block sub-matrix to global memory;
  // each thread writes one element
  const uint c = wB * %(BLOCK_SIZE)s * by + %(BLOCK_SIZE)s * bx;
  C[c + wB * ty + tx] = Csub;
}
"""

# define the (square) matrix size
# Since we want to work with matrices of size 50 mb or so, we need to do some calculations
# to determine what the size of the input sqaure matrices will be
'''
1 float = 8 bits
50 mb = 50 * 1024 * 1024
Total number of floats required in matrices = 50 * 1024 * 1024 / 8

Using this, the size of the matrix = sqrt(50 * 1024 * 1024 / 8) = 2560
Hence, to manipulate matrices of size 50 mb each, we need to set the size of the matrix as 2560 x 2560
'''
MATRIX_SIZE = 2560 

# define size of blocks and tiles sub-matrix 
# (we assume that the block size is same as tile size)
# pycuda will assign a particular number of threads to each block
# checking the output of dump_properties.py file, we see that we can have at most
# 1024 threads per block
# as long as the total number of elements in a tile are less than 1024, pycuda can execute this code without any problems 
TILE_SIZE = 32 
BLOCK_SIZE = TILE_SIZE

# create two random square matrices, each of size 50 mb
a_cpu = np.random.randn(MATRIX_SIZE, MATRIX_SIZE).astype(np.float32)
b_cpu = np.random.randn(MATRIX_SIZE, MATRIX_SIZE).astype(np.float32)

# compute reference on the CPU to verify GPU computation
c_cpu = np.dot(a_cpu, b_cpu)

# transfer host (CPU) memory to device (GPU) memory 
a_gpu = gpuarray.to_gpu(a_cpu) 
b_gpu = gpuarray.to_gpu(b_cpu)

# create empty gpu array for the result (C = A * B)
c_gpu = gpuarray.empty((MATRIX_SIZE, MATRIX_SIZE), np.float32)

# get the kernel code from the template 
# by specifying the constants MATRIX_SIZE and BLOCK_SIZE
kernel_code = kernel_code_template % { 
    'MATRIX_SIZE': MATRIX_SIZE,
    'BLOCK_SIZE': BLOCK_SIZE,
    }

# compile the kernel code
mod = compiler.SourceModule(kernel_code)

# get the kernel function from the compiled module
matrixmul = mod.get_function("MatrixMulKernel")

# call the kernel on the card
matrixmul(
    # inputs
    a_gpu, b_gpu, 
    # output
    c_gpu, 
    # grid of multiple blocks
    grid = (MATRIX_SIZE // TILE_SIZE, MATRIX_SIZE // TILE_SIZE),
    # block of multiple threads
    block = (TILE_SIZE, TILE_SIZE, 1), 
    )

# print the results
print "-" * 80
print "Matrix A (GPU):"
print a_gpu.get()

print "-" * 80
print "Matrix B (GPU):"
print b_gpu.get()

print "-" * 80
print "Matrix C (GPU):"
print c_gpu.get()

print "-" * 80
print "CPU-GPU difference:"
print c_cpu - c_gpu.get()
print "L2 norm:", la.norm(c_cpu - c_gpu.get())
np.allclose(c_cpu, c_gpu.get())
