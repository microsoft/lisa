// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

public static class Program
{
    public static void Main(string[] args)
    {
        long targetBytes = long.Parse(args[0], CultureInfo.InvariantCulture);
        int randomPercentage = int.Parse(args[1], CultureInfo.InvariantCulture);
        string readyPath = args[2];
        int megabyte = 1024 * 1024;
        Random random = new Random();
        List<byte[]> buffers = new List<byte[]>();
        long allocated = 0;

        while (allocated < targetBytes)
        {
            byte[] buffer = new byte[(int)Math.Min(megabyte, targetBytes - allocated)];
            if (buffers.Count % 100 < randomPercentage)
            {
                random.NextBytes(buffer);
            }
            buffers.Add(buffer);
            allocated += buffer.Length;
        }

        File.WriteAllText(
            readyPath,
            targetBytes.ToString(CultureInfo.InvariantCulture));

        while (true)
        {
            int buffersTouched = 0;
            foreach (byte[] buffer in buffers)
            {
                for (int index = 0; index < buffer.Length; index++)
                {
                    if (buffer[index] == 0)
                    {
                        buffer[index] = 255;
                    }
                }

                buffersTouched++;
                if (buffersTouched % 50 == 0)
                {
                    System.Threading.Thread.Sleep(20);
                }
            }
        }
    }
}
